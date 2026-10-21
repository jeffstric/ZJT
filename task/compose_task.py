# -*- coding: utf-8 -*-
"""数字人分段拼接编排任务（compose_job）。

设计定位（见 docs/digital_human_compose_job_plan.md）：
  - 每段是一条**标准** ai_tools(type=35) + tasks(generate_video)，独立计费/退费，
    走既有驱动非分段路径，不再独占 generate_video 调度槽。
  - 本模块是**纯编排器**：只聚合段状态、补缺口段、拼接成片，本身不计费
    （补段重新生成时按新段正常计费，由本模块在段级完成扣费）。

⚠️ 为什么不复用 process_task_with_retry：
  该函数把 task.task_id 硬编码为 ai_tools.id（过期满重试分支会直接改 ai_tools
  并退费）。compose_jobs.id 是小整数，会撞上无关用户的 ai_tools 行，造成
  「误标失败 + 误退费」。因此这里用独立主循环，只复用 tasks 表的
  try_count/next_trigger 通用字段与纯函数（过期判断、退避公式）。

⚠️ tasks 行更新一律用**主键 id**（TasksModel.update(task.id, ...)），
  禁止 update_by_task_id(compose_id)：该接口只按 task_id 过滤、不区分
  task_type，compose_id 可能与某个段的 ai_tools.id 相同而误改段的任务行。
"""
import asyncio
import json
import os
import subprocess
import time
import traceback
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from config.config_util import get_config, get_dynamic_config_value
from config.constant import (
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_COMPLETED,
    AI_TOOL_STATUS_FAILED,
    AI_TOOL_STATUS_SYNC_QUEUED,
    AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
    AI_TOOL_STATUS_WAITING_BEFORE_FINISH,
    AI_TOOL_STATUS_DOWNLOADING,
    TASK_STATUS_QUEUED,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_TYPE_GENERATE_VIDEO,
    TASK_TYPE_COMPOSE_JOB,
    TaskTypeId,
    TaskTypeRegistry,
    ComposeJobStatus,
    ComposeJobConstants,
    DOWNLOAD_PER_ATTEMPT_TIMEOUT,
)
from model import AIToolsModel, TasksModel
from model.compose_jobs import ComposeJobModel
from model.ai_tools_log import AIToolsLogEvent, AIToolsLogModel
from perseids_server.client import make_perseids_request
from utils.audio_duration_util import _get_ffmpeg_path, _get_ffprobe_path
from utils.computing_power import (
    build_refund_transaction_id,
    is_already_refunded,
    resolve_refund_amount,
)
from utils.project_path import resolve_upload_url_to_local_path
from utils.sentry_util import SentryUtil
from utils.media_cache import get_cache_manager
from utils.content_moderation_error import (
    classify_content_moderation,
    is_content_moderation_user_message,
)
from task.visual_task import _check_task_expiration

logger = logging.getLogger(__name__)

# 模块级长寿线程池（AGENTS.md R9/R10：禁止 with 上下文管理器，future.result 必须带 timeout）
_CONCAT_EXECUTOR = ThreadPoolExecutor(
    max_workers=ComposeJobConstants.CONCAT_EXECUTOR_MAX_WORKERS,
    thread_name_prefix="dh-compose",
)

# ai_tools 状态分类（分段状态机用）
_IN_FLIGHT_STATUS = {
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_SYNC_QUEUED,
    AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
    AI_TOOL_STATUS_WAITING_BEFORE_FINISH,
    AI_TOOL_STATUS_DOWNLOADING,
}


# ==================== 通用小工具 ====================

def _retry_delay_seconds(try_count: int) -> int:
    """与 visual_task.calculate_next_retry_delay 同公式（3s 起指数退避，96s 封顶）。

    此处独立实现以避开 compose_task ↔ visual_task 的模块级 import 耦合；
    公式变更时两处必须同步（visual_task 的封顶由 VIDEO_TASK_RETRY_DELAY_MAX_SECONDS 控制）。
    """
    delay = 3 * (2 ** max(try_count - 1, 0))
    return min(delay, 96)


def _schedule_next(task, delay_seconds: int, try_count: Optional[int] = None) -> None:
    """按主键重排 compose 调度行（只动本行，绝不影响同 id 的段任务行）。"""
    fields = {'next_trigger': datetime.now() + timedelta(seconds=delay_seconds)}
    if try_count is not None:
        fields['try_count'] = try_count
    TasksModel.update(task.id, **fields)


def _compose_log(user_id: Optional[int], message: str, detail: Optional[Dict[str, Any]] = None) -> None:
    """compose 侧审计：写应用日志（事件事件日志见 _compose_event）。"""
    try:
        logger.info(f"[compose_job] {message} detail={json.dumps(detail or {}, ensure_ascii=False)}")
    except Exception:
        logger.info(f"[compose_job] {message}")


def _compose_event(compose_id: int, event_type: str, message: str, *,
                   user_id: Optional[int] = None,
                   detail: Optional[Dict[str, Any]] = None,
                   status_from: Optional[int] = None,
                   status_to: Optional[int] = None,
                   try_count: Optional[int] = None) -> None:
    """compose 事件落 ai_tools_log（ai_tool_id 为空，project_id=compose_<id>）。

    compose 在 ai_tools 表里没有记录，段级日志也覆盖不到编排决策，因此这里用
    `project_id='compose_<id>'` 独立落一条时间线。管理后台可直接查：
    `GET /api/admin/ai-tools/timeline?project_id=compose_<id>`
    （api/admin.py:481 的 project_id 参数本就是 str + list_by_project_id）。

    事件类型复用段级既有枚举（AIToolsLogEvent），后台中文标签无需改动。
    `log()` 内部已 best-effort（永不抛），此处仅兜底极端情况。
    """
    try:
        AIToolsLogModel.log(
            None, event_type,
            project_id=f"{ComposeJobConstants.PROJECT_ID_PREFIX}{compose_id}",
            user_id=user_id,
            message=message,
            detail=detail,
            status_from=status_from,
            status_to=status_to,
            try_count=try_count,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[compose_job] 写事件日志失败 compose={compose_id}: {e}")


def _segment_power(duration: int) -> int:
    """段计价（与端点同源：TaskTypeRegistry 的档位表）。"""
    config = TaskTypeRegistry.get(TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3)
    if not config:
        return 0
    try:
        return config.get_computing_power(duration=duration) or 0
    except Exception as e:
        logger.warning(f"[compose_job] 段计价失败 duration={duration}: {e}")
        return 0


def _charge_segment(user_id: int, power: int, transaction_id: str) -> bool:
    """补段扣费（同步，调度线程内执行）。失败仅记日志并返回 False（不建段）。"""
    if not power:
        return True
    try:
        success, message, response_data = make_perseids_request(
            endpoint='get_auth_token_by_user_id',
            method='POST',
            data={"user_id": user_id}
        )
        if not success:
            logger.error(f"[compose_job] 补段取 token 失败 user={user_id}: {message}")
            return False
        headers = {'Authorization': f"Bearer {response_data['token']}"}
        success, message, _ = make_perseids_request(
            endpoint='user/calculate_computing_power',
            method='POST',
            headers=headers,
            data={
                "computing_power": power,
                "behavior": "deduct",
                "transaction_id": transaction_id
            }
        )
        if not success:
            logger.error(f"[compose_job] 补段扣费失败 user={user_id} power={power}: {message}")
            return False
        return True
    except Exception as e:
        logger.error(f"[compose_job] 补段扣费异常 user={user_id}: {e}")
        return False


def _refund_segment(ai_tool, reason: str) -> None:
    """段退费（幂等：refund-{原扣费流水号}）。用于段被判定为不可用且不由
    调度器负责退费的路径（下载兜底残留降级、补段后旧段清理）。"""
    try:
        if not ai_tool or not getattr(ai_tool, 'user_id', None):
            return
        if is_already_refunded(ai_tool):
            return
        computing_power = resolve_refund_amount(ai_tool)
        if not computing_power:
            return
        transaction_id = build_refund_transaction_id(ai_tool) or str(uuid.uuid4())
        success, message, response_data = make_perseids_request(
            endpoint='get_auth_token_by_user_id',
            method='POST',
            data={"user_id": ai_tool.user_id}
        )
        if not success:
            logger.error(f"[compose_job] 段 {ai_tool.id} 退费取 token 失败: {message}")
            return
        headers = {'Authorization': f"Bearer {response_data['token']}"}
        success, message, _ = make_perseids_request(
            endpoint='user/calculate_computing_power',
            method='POST',
            headers=headers,
            data={
                "computing_power": computing_power,
                "behavior": "increase",
                "transaction_id": transaction_id
            }
        )
        if success:
            logger.info(f"[compose_job] 段 {ai_tool.id} 已退费 {computing_power}（{reason}）")
        else:
            logger.error(f"[compose_job] 段 {ai_tool.id} 退费失败（{reason}）: {message}")
    except Exception as e:
        logger.error(f"[compose_job] 段退费异常（{reason}）: {e}")


# ==================== 段状态判定 ====================

def _segment_local_path(seg) -> Optional[str]:
    """段已完成且文件已落本地 → 返回本地绝对路径；否则 None。

    就绪判据：status=COMPLETED 且 result_url 为 /upload/ 前缀且文件存在。
    段刚 SUCCESS 时 result_url 还是远端 URL，要等 download_queue 落盘。
    """
    url = getattr(seg, 'result_url', None)
    if not url or not isinstance(url, str) or not url.startswith('/upload/'):
        return None
    try:
        path = resolve_upload_url_to_local_path(url)
    except Exception:
        return None
    return path if os.path.isfile(path) else None


def _seg_extra(seg) -> Dict[str, Any]:
    """安全解析段 extra_config（脏 JSON 不得中断编排主循环）。"""
    raw = getattr(seg, 'extra_config', None)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _moderation_failure_reason(seg) -> Optional[str]:
    """段因内容审核失败 → 返回其失败原因；否则 None。

    补段使用与失败段完全相同的 prompt/角色图/音频，审核类失败是**确定性**的，
    补段必然再次失败。虽然标准管线每轮都会退费（资金不损失），但空转最多
    MAX_RETRY_COUNT 轮意味着数小时假 RUNNING + 约 2 倍轮数的计费流水，
    因此命中审核失败时整单直接 FAILED 并把原因透传给用户。
    """
    message = getattr(seg, 'message', None)
    if not message or not isinstance(message, str):
        return None
    try:
        if is_content_moderation_user_message(message):
            return message
        if classify_content_moderation(error_message=message):
            return message
    except Exception:
        return None
    return None


def _bump_download_attempts(seg) -> int:
    """记录 compose 侧自愈下载次数（存在段 extra_config，避免额外表字段）。"""
    extra = _seg_extra(seg)
    attempts = int(extra.get('compose_download_attempts') or 0) + 1
    extra['compose_download_attempts'] = attempts
    try:
        AIToolsModel.update(seg.id, extra_config=json.dumps(extra, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"[compose_job] 段 {seg.id} 记录下载次数失败: {e}")
    return attempts


def _download_remote_to_upload_cache(seg) -> Optional[str]:
    """同步 HTTP 下载远端成片到 upload/cache，返回 /upload/ 路径。

    兜底：媒体缓存未启用或 download_and_cache 失败时使用。不依赖 cache manager
    的 enabled 开关——否则 dev 环境（缓存常关闭）会把「可自愈」误判为「不可用」，
    进而触发**付费重生成**。
    """
    import requests

    url = getattr(seg, 'result_url', None)
    if not url or not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        return None
    date_str = time.strftime('%Y-%m-%d')
    out_dir = os.path.join('upload', 'cache', date_str)
    os.makedirs(out_dir, exist_ok=True)
    filename = f"seg_{seg.id}_heal_{int(time.time())}.mp4"
    out_path = os.path.join(out_dir, filename)
    written = 0
    try:
        with requests.get(url, stream=True, timeout=(10, 120)) as resp:
            if resp.status_code != 200:
                logger.warning(
                    f"[compose_job] 段 {seg.id} 直连下载 HTTP {resp.status_code}: {url[:120]}"
                )
                return None
            with open(out_path, 'wb') as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if chunk:
                        fh.write(chunk)
                        written += len(chunk)
    except Exception as e:
        logger.warning(f"[compose_job] 段 {seg.id} 直连下载异常: {e}")
        try:
            if os.path.isfile(out_path):
                os.remove(out_path)
        except OSError:
            pass
        return None
    if written < 1024:
        try:
            os.remove(out_path)
        except OSError:
            pass
        logger.warning(f"[compose_job] 段 {seg.id} 直连下载文件过小({written}B)，视为失败")
        return None
    return f"/upload/cache/{date_str}/{filename}"


def _self_download_segment(seg) -> Optional[str]:
    """段 COMPLETED 但 result_url 仍为远端（download_queue 兜底残留）时自行下载。

    返回本地 /upload/ URL；失败返回 None（由调用方决定重试 or 降级补段）。
    """
    attempts = _bump_download_attempts(seg)
    if attempts > ComposeJobConstants.SEGMENT_REMOTE_DOWNLOAD_MAX_ATTEMPTS:
        return None

    local_url: Optional[str] = None
    try:
        manager = get_cache_manager()
        if getattr(manager, 'enabled', False):
            local_url = asyncio.run(asyncio.wait_for(
                manager.download_and_cache(seg.result_url, seg.id, 'video', max_retries=1),
                timeout=DOWNLOAD_PER_ATTEMPT_TIMEOUT,
            ))
    except asyncio.TimeoutError:
        logger.warning(f"[compose_job] 段 {seg.id} 缓存下载超时（第 {attempts} 次）")
    except Exception as e:
        logger.warning(f"[compose_job] 段 {seg.id} 缓存下载异常（第 {attempts} 次）: {e}")

    if not local_url or not str(local_url).startswith('/upload/'):
        local_url = _download_remote_to_upload_cache(seg)
    if not local_url:
        return None

    try:
        AIToolsModel.update(seg.id, result_url=local_url)
    except Exception as e:
        logger.warning(f"[compose_job] 段 {seg.id} 回写本地 result_url 失败: {e}")
        return None
    # 同步内存对象：否则本轮的「未就绪」判定仍按远端 URL 走，白等一轮
    try:
        seg.result_url = local_url
    except Exception:
        pass
    logger.info(f"[compose_job] 段 {seg.id} 兜底残留已自愈为本地文件: {local_url}")
    return local_url


# ==================== 补段 ====================

def _segment_audio_available(job, idx: int) -> bool:
    """补段前置校验：参数快照里有该段时长，且段音频文件仍在本地。

    段音频是端点落盘的临时上传文件（upload/temp），可能已被清理。若不先校验，
    补段会「扣费 → 建段 → 驱动上传音频失败 → 段终态失败退费」反复循环，
    每次都要等一轮完整生命周期，最终把重试预算耗尽。
    """
    params = job.params or {}
    paths = params.get('segment_paths') or []
    durations = params.get('segment_durations') or []
    if idx >= len(paths) or idx >= len(durations):
        return False
    try:
        local_path = resolve_upload_url_to_local_path(paths[idx])
    except Exception:
        return False
    return os.path.isfile(local_path)


def _segment_image_available(job) -> bool:
    """补段前置校验：角色图仍在本地。

    角色图同样是 upload/temp 临时文件；缺失时补段必然在上传图床阶段失败，
    同样是「扣费→失败→退费」的空转。
    """
    image_url = (job.params or {}).get('image_url')
    if not image_url:
        # 参数快照未记录（历史单/其他入口）：不做判定，按原路径尝试补段
        return True
    try:
        return os.path.isfile(resolve_upload_url_to_local_path(image_url))
    except Exception:
        return False


def _refill_segment(job, task, seg_index: int) -> Optional[int]:
    """为缺口段新建标准 ai_tools + tasks（重新计费），返回新段 id。

    顺序维护：调用方必须按 seg_index **原位替换** job.segment_ai_tool_ids，
    禁止尾部追加（会打乱拼接顺序）。
    """
    params = job.params or {}
    durations = params.get('segment_durations') or []
    paths = params.get('segment_paths') or []
    if seg_index >= len(durations) or seg_index >= len(paths):
        logger.error(
            f"[compose_job] compose={job.id} 段 {seg_index} 缺参数快照，无法补段"
        )
        _compose_event(
            job.id, AIToolsLogEvent.EXCEPTION,
            f"补段失败：段 {seg_index + 1} 缺参数快照",
            user_id=job.user_id, detail={'seg_index': seg_index + 1})
        return None

    seg_duration = durations[seg_index]
    audio_path = paths[seg_index]
    power = _segment_power(seg_duration)
    transaction_id = str(uuid.uuid4())

    # 先扣费再建记录：扣费失败不建段（避免「有记录无扣费」的免费额度）
    if not _charge_segment(job.user_id, power, transaction_id):
        _compose_event(
            job.id, AIToolsLogEvent.EXCEPTION,
            f"补段扣费未成功（段 {seg_index + 1}，{power} 算力），本轮不建段",
            user_id=job.user_id,
            detail={'seg_index': seg_index + 1, 'power': power,
                    'transaction_id': transaction_id})
        return None

    extra_config = json.dumps({
        "max_edge": params.get('max_edge', 1280),
        "start_second": params.get('start_second', 0),
        "seg_index": seg_index + 1,
        "dh_segment": True,
        "compose_id": job.id,
        "compose_refill": True,
    }, ensure_ascii=False)

    seg_id: Optional[int] = None
    try:
        seg_id = AIToolsModel.create(
            prompt=params.get('prompt') or '',
            user_id=job.user_id,
            type=TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
            image_path=params.get('image_url'),
            audio_path=audio_path,
            duration=seg_duration,
            extra_config=extra_config,
            transaction_id=transaction_id,
            status=AI_TOOL_STATUS_PENDING
        )
        TasksModel.create(
            task_type=TASK_TYPE_GENERATE_VIDEO,
            task_id=seg_id,
            status=TASK_STATUS_QUEUED
        )
        try:
            from task.pipeline_processor import PipelineProcessor
            PipelineProcessor.attach_param_prepare_if_needed(
                seg_id, TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3)
        except Exception as e:
            logger.warning(f"[compose_job] 补段 {seg_id} param_prepare 失败: {e}")
    except Exception as e:
        logger.error(f"[compose_job] compose={job.id} 段 {seg_index} 建记录失败: {e}")
        # 段主记录已建但调度行未建成 → 先把段置 FAILED，避免留下永远 PENDING 的脏数据
        if seg_id:
            try:
                AIToolsModel.update(
                    seg_id,
                    status=AI_TOOL_STATUS_FAILED,
                    message="补段建调度行失败，已退费取消",
                    completed_time=datetime.now())
            except Exception as mark_err:
                logger.warning(f"[compose_job] 补段 {seg_id} 置失败异常: {mark_err}")
        # 已扣费但未建成记录 → 立即原额退回
        try:
            _refund_by_transaction(job.user_id, transaction_id, power, "补段建记录失败")
        except Exception as refund_err:
            logger.error(f"[compose_job] 补段扣费回滚失败 {transaction_id}: {refund_err}")
        _compose_event(
            job.id, AIToolsLogEvent.EXCEPTION,
            f"补段建记录失败（段 {seg_index + 1}），已原额退回 {power} 算力: {e}",
            user_id=job.user_id,
            detail={'seg_index': seg_index + 1, 'power': power,
                    'transaction_id': transaction_id, 'error': str(e)})
        return None

    logger.info(
        f"[compose_job] compose={job.id} 补段 seg_index={seg_index} -> ai_tool={seg_id} "
        f"duration={seg_duration}s power={power}"
    )
    _compose_event(
        job.id, AIToolsLogEvent.PIPELINE_STEP,
        f"补段成功：段 {seg_index + 1} → ai_tool {seg_id}（{seg_duration}s，{power} 算力）",
        user_id=job.user_id,
        detail={'seg_index': seg_index + 1, 'segment_ai_tool_id': seg_id,
                'duration': seg_duration, 'power': power,
                'transaction_id': transaction_id})
    return seg_id


def _refund_by_transaction(user_id: int, transaction_id: str, power: int, reason: str) -> None:
    """按扣费流水原额退回（refund-{原流水号} 幂等）。"""
    if not power:
        return
    success, message, response_data = make_perseids_request(
        endpoint='get_auth_token_by_user_id', method='POST', data={"user_id": user_id}
    )
    if not success:
        logger.error(f"[compose_job] 回滚取 token 失败 user={user_id}: {message}")
        return
    headers = {'Authorization': f"Bearer {response_data['token']}"}
    success, message, _ = make_perseids_request(
        endpoint='user/calculate_computing_power',
        method='POST',
        headers=headers,
        data={
            "computing_power": power,
            "behavior": "increase",
            "transaction_id": f"refund-{transaction_id}"
        }
    )
    if success:
        logger.info(f"[compose_job] 已退回 {power} 算力（{reason}）流水 {transaction_id}")
    else:
        logger.error(f"[compose_job] 退回失败（{reason}）流水 {transaction_id}: {message}")


# ==================== 拼接 ====================

def _concat_videos(project_id: str, seg_files: List[str]) -> str:
    """统一缩放到首段尺寸后拼接，落盘 upload/cache 并返回 /upload/ 路径。

    ffmpeg 参数与旧驱动内分段流水线一致（首段尺寸基准 + yuv420p + aac），
    但超时走 compose 专属常量（AGENTS.md #9）；执行在线程池中（R10）。
    """
    probe = subprocess.run(
        [_get_ffprobe_path(), '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height', '-of', 'json', seg_files[0]],
        capture_output=True, text=True, timeout=60)
    stream = (json.loads(probe.stdout or '{}').get('streams') or [{}])[0]
    out_w = int(stream.get('width') or 960)
    out_h = int(stream.get('height') or 1280)
    out_h += out_h % 2

    date_str = time.strftime('%Y-%m-%d')
    out_dir = os.path.join('upload', 'cache', date_str)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(
        out_dir, f"{project_id}_h3compose_{time.strftime('%H%M%S')}.mp4")

    inputs: List[str] = []
    for path in seg_files:
        inputs += ['-i', path]
    scale_chain = ';'.join(
        f'[{i}:v]scale={out_w}:{out_h},format=yuv420p[v{i}]'
        for i in range(len(seg_files)))
    concat_filter = scale_chain + ';' \
        + ''.join(f'[v{i}][{i}:a]' for i in range(len(seg_files))) \
        + f'concat=n={len(seg_files)}:v=1:a=1[v][a]'

    result = subprocess.run(
        [_get_ffmpeg_path(), '-y', '-loglevel', 'error', *inputs,
         '-filter_complex', concat_filter, '-map', '[v]', '-map', '[a]',
         '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-c:a', 'aac', out_path],
        capture_output=True, text=True,
        timeout=ComposeJobConstants.CONCAT_TIMEOUT_SECONDS)
    if result.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"ffmpeg 拼接失败: {(result.stderr or '')[-300:]}")
    logger.info(f"[compose_job] 拼接完成 project={project_id}: {out_path} ({out_w}x{out_h})")
    return f"/upload/cache/{date_str}/{os.path.basename(out_path)}"


def _concat_with_timeout(project_id: str, seg_files: List[str]) -> str:
    """提交到长寿线程池并显式超时等待（R9/R10）。"""
    future = _CONCAT_EXECUTOR.submit(_concat_videos, project_id, seg_files)
    return future.result(timeout=ComposeJobConstants.CONCAT_TIMEOUT_SECONDS + 60)


def _attach_cdn_mapping(job, local_url: str) -> Optional[int]:
    """拼接成片建 media_file_mapping 并触发 CDN 上传（实体类型 COMPOSE_JOB）。"""
    enable_cdn = get_config().get("server", {}).get("auto_upload_to_cdn", False)
    if not enable_cdn or not local_url or not local_url.startswith('/upload/'):
        return None
    try:
        from model.media_file_mapping import MediaFileMappingModel, MediaFileEntity
        from config.media_file_policy import MediaFilePolicy
        from utils.mime_type import get_mime_type_from_extension
        from utils.cdn_util import CDNUtil

        local_path = local_url.lstrip('/')
        media_type = get_mime_type_from_extension(os.path.splitext(local_url)[1].lower())
        file_size = os.path.getsize(local_path) if os.path.exists(local_path) else None
        mapping_id = MediaFileMappingModel.create(
            user_id=job.user_id,
            local_path=local_path,
            cloud_path=None,
            policy_code=MediaFilePolicy.MEDIA_CACHE,
            entity_type=MediaFileEntity.COMPOSE_JOB,
            source_id=job.id,
            media_type=media_type,
            original_url=None,
            file_size=file_size,
        )
        CDNUtil.trigger_cdn_upload(mapping_id, local_path)
        logger.info(f"[compose_job] compose={job.id} CDN mapping={mapping_id}")
        return mapping_id
    except Exception as e:
        logger.error(f"[compose_job] compose={job.id} 建 CDN mapping 失败: {e}")
        return None


# ==================== 终态 ====================

def _finish_compose(task, job, status: int, message: Optional[str],
                    result_url: Optional[str] = None,
                    media_mapping_id: Optional[int] = None) -> None:
    """compose 终态收尾：编排表 + 调度行必须同时落终态（防重复调度）。"""
    # message 列为 varchar(500)：拼接异常栈/上游长文案直接写入会触发
    # "Data too long"，导致终态写库失败、任务被反复调度
    safe_message = (str(message) if message else None)
    if safe_message and len(safe_message) > 500:
        safe_message = safe_message[:497] + '...'
    fields: Dict[str, Any] = {'status': status, 'message': safe_message}
    if result_url is not None:
        fields['result_url'] = result_url
    if media_mapping_id is not None:
        fields['media_mapping_id'] = media_mapping_id
    ComposeJobModel.update(job.id, **fields)

    task_status = TASK_STATUS_COMPLETED if status == ComposeJobStatus.COMPLETED else TASK_STATUS_FAILED
    TasksModel.update(task.id, status=task_status)
    log_msg = f"compose={job.id} 终态 status={status} message={message}"
    if status == ComposeJobStatus.COMPLETED:
        logger.info(f"[compose_job] {log_msg} result={result_url}")
        _compose_event(
            job.id, AIToolsLogEvent.TASK_COMPLETED, f"拼接完成: {message or ''}".strip(),
            user_id=getattr(job, 'user_id', None),
            status_from=getattr(job, 'status', None), status_to=status,
            detail={'result_url': result_url, 'media_mapping_id': media_mapping_id})
    else:
        logger.error(f"[compose_job] {log_msg}")
        _compose_event(
            job.id, AIToolsLogEvent.MAX_RETRY_EXCEEDED,
            f"编排终态失败: {message or ''}".strip(),
            user_id=getattr(job, 'user_id', None),
            status_from=getattr(job, 'status', None), status_to=status,
            detail={'result_url': result_url})
        try:
            SentryUtil.capture_message(f"[compose_job] 拼接失败: {message}")
        except Exception:
            pass


# ==================== 单编排任务处理 ====================

def _process_one_compose(task) -> None:
    """处理单个 compose 任务（task.task_id = compose_jobs.id）。"""
    try:
        compose_id = int(task.task_id)
    except (TypeError, ValueError):
        logger.error(f"[compose_job] 非法 task_id={task.task_id}，置失败")
        TasksModel.update(task.id, status=TASK_STATUS_FAILED)
        return

    job = ComposeJobModel.get_by_id(compose_id)
    if not job:
        logger.error(f"[compose_job] compose={compose_id} 记录不存在，置失败")
        TasksModel.update(task.id, status=TASK_STATUS_FAILED)
        return

    # 已终态（重复调度/重启残留）：只补收尾 tasks 行
    if job.is_terminal:
        TasksModel.update(
            task.id,
            status=TASK_STATUS_COMPLETED if job.status == ComposeJobStatus.COMPLETED else TASK_STATUS_FAILED,
        )
        return

    # 过期保护（复用 ai_tools 的 task_expire_days 配置语义，仅看 created_at）
    try:
        if _check_task_expiration(task):
            _finish_compose(task, job, ComposeJobStatus.FAILED, "拼接任务已过期")
            return
    except Exception as e:
        logger.warning(f"[compose_job] 过期检查异常（忽略）: {e}")

    if task.status == TASK_STATUS_QUEUED:
        TasksModel.update(task.id, status=TASK_STATUS_PROCESSING)
        _compose_event(
            compose_id, AIToolsLogEvent.TASK_STARTED, "编排任务开始处理",
            user_id=job.user_id,
            status_from=TASK_STATUS_QUEUED, status_to=TASK_STATUS_PROCESSING,
            detail={'segments': len(job.segment_ai_tool_ids or [])})

    seg_ids = list(job.segment_ai_tool_ids or [])
    if not seg_ids:
        _finish_compose(task, job, ComposeJobStatus.FAILED, "编排任务无段记录")
        return

    segments = [AIToolsModel.get_by_id(sid) for sid in seg_ids]

    # ---------- 1) 收集缺口（终态失败 / 记录缺失）----------
    gaps: List[int] = [
        idx for idx, seg in enumerate(segments)
        if seg is None or seg.status == AI_TOOL_STATUS_FAILED
    ]

    # ---------- 1.5) 审核类确定性失败 → 整单快速失败（补段用相同输入必然再败）----------
    if gaps:
        for idx in gaps:
            seg = segments[idx]
            if seg is None:
                continue
            reason = _moderation_failure_reason(seg)
            if reason:
                logger.warning(
                    f"[compose_job] compose={compose_id} 段 {seg.id} 命中内容审核，"
                    f"整单失败（不补段）: {str(reason)[:120]}"
                )
                _compose_event(
                    compose_id, AIToolsLogEvent.UPSTREAM_FAILED,
                    f"段 {idx + 1} 内容审核未通过，整单终止",
                    user_id=job.user_id,
                    status_from=AI_TOOL_STATUS_FAILED, status_to=ComposeJobStatus.FAILED,
                    detail={'segment_id': seg.id, 'seg_index': idx + 1,
                            'reason': str(reason)[:300]})
                _finish_compose(task, job, ComposeJobStatus.FAILED, reason)
                return

    # ---------- 2) 兜底残留自愈（COMPLETED 但 result_url 非本地）----------
    if not gaps:
        healed_this_round = 0
        for idx, seg in enumerate(segments):
            if seg.status != AI_TOOL_STATUS_COMPLETED:
                continue
            if _segment_local_path(seg):
                continue
            if healed_this_round >= ComposeJobConstants.SEGMENT_HEAL_PER_ROUND:
                # 自愈是同步 HTTP 下载，一轮只处理有限个，避免长时间占用调度线程
                logger.info(
                    f"[compose_job] compose={compose_id} 本轮自愈已达上限"
                    f"（{ComposeJobConstants.SEGMENT_HEAL_PER_ROUND}），余下次轮"
                )
                break
            healed_this_round += 1
            # dump 状态：先尝试自行下载（有限次）
            local_url = _self_download_segment(seg)
            if local_url:
                _compose_event(
                    compose_id, AIToolsLogEvent.DOWNLOAD_COMPLETED,
                    f"段 {seg.id} 下载兜底残留已自愈为本地文件",
                    user_id=job.user_id,
                    detail={'segment_id': seg.id, 'local_url': local_url})
                continue
            attempts = int(_seg_extra(seg).get('compose_download_attempts') or 0)
            if attempts >= ComposeJobConstants.SEGMENT_REMOTE_DOWNLOAD_MAX_ATTEMPTS:
                logger.warning(
                    f"[compose_job] compose={compose_id} 段 {seg.id} 远端残留自愈失败"
                    f"（{attempts} 次），降级为缺口补段"
                )
                AIToolsModel.update(
                    seg.id, status=AI_TOOL_STATUS_FAILED,
                    message="结果文件无法本地化，已降级重生成",
                    completed_time=datetime.now())
                _refund_segment(seg, "结果文件无法本地化")
                _compose_event(
                    compose_id, AIToolsLogEvent.UPSTREAM_FAILED,
                    f"段 {seg.id} 结果无法本地化（自愈 {attempts} 次），已退费并降级重生成",
                    user_id=job.user_id,
                    status_from=AI_TOOL_STATUS_COMPLETED, status_to=AI_TOOL_STATUS_FAILED,
                    detail={'segment_id': seg.id, 'attempts': attempts})
                gaps.append(idx)
            else:
                # 仍未到上限：本轮先按等待处理（下轮再试）
                logger.info(
                    f"[compose_job] compose={compose_id} 段 {seg.id} 远端残留，"
                    f"第 {attempts} 次自愈未成功，稍后重试"
                )

    # ---------- 3) 有缺口 → 补段（重新计费）----------
    if gaps:
        if not _segment_image_available(job):
            _finish_compose(
                task, job, ComposeJobStatus.FAILED,
                "角色图文件缺失，无法补段（请重新提交任务）"
            )
            return
        missing_audio = [idx for idx in gaps if not _segment_audio_available(job, idx)]
        if missing_audio:
            _finish_compose(
                task, job, ComposeJobStatus.FAILED,
                f"段音频文件缺失，无法补段（段序号 {[i + 1 for i in missing_audio]}）"
            )
            return
        if task.try_count and task.try_count >= ComposeJobConstants.MAX_RETRY_COUNT:
            _finish_compose(
                task, job, ComposeJobStatus.FAILED,
                f"补段超过最大重试次数({ComposeJobConstants.MAX_RETRY_COUNT})"
            )
            return

        new_try_count = (task.try_count or 0) + 1
        refilled = False
        current_ids = list(seg_ids)
        for idx in gaps:
            new_seg_id = _refill_segment(job, task, idx)
            if not new_seg_id:
                continue
            current_ids[idx] = new_seg_id          # 原位替换，保持拼接顺序
            refilled = True
        if refilled:
            ComposeJobModel.update_segment_ids(compose_id, current_ids)
            # 段已更换：拼接熔断计数清零（此前的拼接失败可能正是坏段导致的）
            ComposeJobModel.update(compose_id, concat_attempts=0)
            logger.info(
                f"[compose_job] compose={compose_id} 补段完成 gaps={gaps} try={new_try_count}"
                f" ids={current_ids}"
            )
            _compose_event(
                compose_id, AIToolsLogEvent.RETRY_SCHEDULED,
                f"补段 {len(gaps)} 个并重新计费（第 {new_try_count} 次），"
                f"{_retry_delay_seconds(new_try_count)}s 后复查",
                user_id=job.user_id, try_count=new_try_count,
                detail={'gaps': [i + 1 for i in gaps], 'segment_ids': current_ids})
        else:
            _compose_event(
                compose_id, AIToolsLogEvent.EXCEPTION,
                f"补段未成功（{len(gaps)} 个缺口全部失败），"
                f"{_retry_delay_seconds(new_try_count)}s 后重试",
                user_id=job.user_id, try_count=new_try_count,
                detail={'gaps': [i + 1 for i in gaps]})
        delay = _retry_delay_seconds(new_try_count)
        _schedule_next(task, delay, try_count=new_try_count)
        job_msg = f"补段 {len(gaps)} 个（第 {new_try_count} 次）"
        ComposeJobModel.update(compose_id, message=job_msg[:500])
        _compose_log(job.user_id, job_msg, {'gaps': gaps, 'segment_ids': current_ids})
        return

    # ---------- 4) 还有段在途 → 等待（不消耗重试预算）----------
    in_flight = [seg for seg in segments if seg and seg.status in _IN_FLIGHT_STATUS]
    if in_flight:
        _schedule_next(task, ComposeJobConstants.WAIT_RESCHEDULE_SECONDS)
        return

    # ---------- 5) 兜底残留仍在有限次自愈窗口内 → 等待 ----------
    remote_pending = [
        seg for seg in segments
        if seg and seg.status == AI_TOOL_STATUS_COMPLETED and not _segment_local_path(seg)
    ]
    if remote_pending:
        _schedule_next(task, ComposeJobConstants.WAIT_RESCHEDULE_SECONDS)
        return

    # ---------- 6) 全部就绪 → 拼接 ----------
    seg_files: List[str] = []
    for idx, seg in enumerate(segments):
        path = _segment_local_path(seg)
        if not path:
            # 理论上不会到这里（上面已分类），保守回退为等待
            logger.warning(f"[compose_job] compose={compose_id} 段 {idx} 本地文件缺失，等待下轮")
            _schedule_next(task, ComposeJobConstants.WAIT_RESCHEDULE_SECONDS)
            return
        seg_files.append(path)

    ComposeJobModel.update(compose_id, status=ComposeJobStatus.COMPOSING, message="拼接中")
    _compose_event(
        compose_id, AIToolsLogEvent.PIPELINE_STEP, f"开始拼接 {len(seg_files)} 段",
        user_id=job.user_id,
        status_from=getattr(job, 'status', None), status_to=ComposeJobStatus.COMPOSING,
        detail={'segments': len(seg_files), 'seg_files': seg_files})

    try:
        result_url = _concat_with_timeout(f"compose_{compose_id}", seg_files)
    except Exception as e:
        logger.error(f"[compose_job] compose={compose_id} 拼接失败: {e}")
        concat_attempts = int(getattr(job, 'concat_attempts', 0) or 0) + 1
        # 拼接失败多为确定性错误（文件损坏/缺音轨/滤镜不兼容），
        # 用补段的 100 次预算重试会在退避封顶 96s 下空转数小时，故独立熔断
        if concat_attempts >= ComposeJobConstants.CONCAT_MAX_ATTEMPTS:
            _finish_compose(
                task, job, ComposeJobStatus.FAILED,
                f"拼接连续失败 {concat_attempts} 次: {e}"
            )
            return
        _compose_event(
            compose_id, AIToolsLogEvent.EXCEPTION,
            f"拼接失败（第 {concat_attempts}/{ComposeJobConstants.CONCAT_MAX_ATTEMPTS} 次），"
            f"{_retry_delay_seconds(concat_attempts)}s 后重试: {e}",
            user_id=job.user_id,
            status_from=ComposeJobStatus.COMPOSING, status_to=ComposeJobStatus.PENDING,
            detail={'concat_attempts': concat_attempts, 'error': str(e)})
        ComposeJobModel.update(
            compose_id, status=ComposeJobStatus.PENDING,
            concat_attempts=concat_attempts,
            message=f"拼接失败，重试中（第 {concat_attempts} 次）: {e}"[:500])
        # 不写 try_count：该计数属补段预算，拼接失败有自己的 concat_attempts
        _schedule_next(task, _retry_delay_seconds(concat_attempts))
        return

    mapping_id = _attach_cdn_mapping(job, result_url)
    _finish_compose(
        task, job, ComposeJobStatus.COMPLETED, "拼接完成",
        result_url=result_url, media_mapping_id=mapping_id)


# ==================== 主循环 ====================

def process_compose_jobs(app=None) -> None:
    """compose 专用主循环（调度器每 5s 触发，max_instances=1）。

    遍历 status∈{QUEUED, PROCESSING} 且 next_trigger<=NOW() 的 compose_job 行，
    逐单推进状态机；单条异常只影响自身（记日志 + 退避），不中断整批。
    """
    try:
        tasks = TasksModel.list_by_type_and_status(
            TASK_TYPE_COMPOSE_JOB,
            status_list=[TASK_STATUS_QUEUED, TASK_STATUS_PROCESSING]
        )
        if not tasks:
            return

        logger.info(f"[compose_job] 待处理编排任务 {len(tasks)} 个")
        for task in tasks:
            try:
                _process_one_compose(task)
            except Exception as e:
                logger.error(f"[compose_job] 处理异常 task_id={task.task_id}: {e}")
                logger.error(traceback.format_exc())
                try:
                    new_try_count = (task.try_count or 0) + 1
                    if new_try_count >= ComposeJobConstants.MAX_RETRY_COUNT:
                        job = ComposeJobModel.get_by_id(int(task.task_id)) \
                            if str(task.task_id).isdigit() else None
                        if job:
                            _finish_compose(task, job, ComposeJobStatus.FAILED, f"处理异常: {e}")
                        else:
                            TasksModel.update(task.id, status=TASK_STATUS_FAILED)
                    else:
                        _schedule_next(task, _retry_delay_seconds(new_try_count),
                                       try_count=new_try_count)
                except Exception as inner:
                    logger.error(f"[compose_job] 异常后调度失败 task_id={task.task_id}: {inner}")
    except Exception as e:
        logger.error(f"[compose_job] 主循环异常: {e}")
        logger.error(traceback.format_exc())
