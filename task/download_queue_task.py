"""
下载队列消费者 job

每 DOWNLOAD_POLL_INTERVAL 秒由 scheduler 触发（经 _run_async_task 包装，跑在临时事件循环里）。
从 download_queue 表 claim 一批 pending 行，asyncio.gather 并发下载；成功则更新 ai_tools
（COMPLETED + 本地/CDN URL），失败按退避重试，达 max_try 用 remote_url 兜底 COMPLETED。

⚠️ 设计要点：
- while 持续满载到队列空，但单次 tick 受 DOWNLOAD_MAX_BATCHES_PER_TICK 限制，
  防止队列积压时单次 job 永不返回、退化成新阻塞源（M2）
- 单次下载 wait_for(DOWNLOAD_PER_ATTEMPT_TIMEOUT) 兜底，避免协程卡死；内层 max_retries=1
  不再自重试，重试由本层 reschedule + 退避统一控制（避免与内层重试层次冲突）
- 租约 lease_until：worker 崩溃的行会被下个 tick 的 claim 回收（P1），
  因此 DOWNLOAD_LEASE_SECONDS 必须 > 下载超时 + 视频后处理预算 + 完成余量（M3）
- 用 get_cache_manager().download_and_cache（类方法），失败返回 None 可区分；
  不用模块级便捷函数（它失败时回退原 URL 会误判成功）
"""
import asyncio
import os
import socket
from datetime import datetime, timedelta
from typing import Optional
import logging

from config.constant import (
    DOWNLOAD_DISPATCHER_CONCURRENCY,
    DOWNLOAD_MAX_BATCHES_PER_TICK,
    DOWNLOAD_PER_ATTEMPT_TIMEOUT,
    DOWNLOAD_LEASE_SECONDS,
    DOWNLOAD_MAX_TRY,
    DOWNLOAD_BACKOFF_SECONDS,
    DOWNLOAD_COMPLETION_MARGIN_SECONDS,
    AI_TOOL_STATUS_COMPLETED,
    GeneratedVideoFaceGridTrimConstants,
)
from model.download_queue import DownloadQueueModel
from model.ai_tools import AIToolsModel
from model.ai_tools_log import AIToolsLogModel, AIToolsLogEvent
from services.generated_video_face_grid_service import maybe_trim_generated_face_grid_prefix
from utils.media_cache import get_cache_manager

logger = logging.getLogger(__name__)


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _backoff_seconds(try_count: int) -> int:
    """按 try_count 取退避秒数，越界取末值"""
    if not DOWNLOAD_BACKOFF_SECONDS:
        return 30
    return DOWNLOAD_BACKOFF_SECONDS[min(try_count, len(DOWNLOAD_BACKOFF_SECONDS) - 1)]


def _safe_task_id(val) -> Optional[int]:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _log(task_id, event, **kwargs):
    """日志包装，失败不影响主流程（P8：下载环节日志挪到 worker）"""
    try:
        AIToolsLogModel.log(task_id, event, **kwargs)
    except Exception as e:
        logger.warning(f"AIToolsLog {event} failed for task {task_id}: {e}")


async def _process_one(row: dict) -> None:
    """处理单条下载：成功→COMPLETED；失败→退避重试 / 达上限 remote_url 兜底"""
    row_id = row['id']
    ai_tool_id = row['ai_tool_id']
    task_id = _safe_task_id(ai_tool_id)
    project_id = row.get('project_id')
    remote_url = row['remote_url']
    media_type = row.get('media_type') or 'video'
    try_count = row.get('try_count', 0) or 0
    max_try = row.get('max_try') or DOWNLOAD_MAX_TRY
    create_at = row.get('create_at')

    queue_wait_ms = None
    if create_at:
        try:
            queue_wait_ms = int((datetime.now() - create_at).total_seconds() * 1000)
        except Exception:
            queue_wait_ms = None

    download_start = datetime.now()
    err = None
    try:
        local_url = await asyncio.wait_for(
            get_cache_manager().download_and_cache(remote_url, ai_tool_id, media_type, max_retries=1),
            timeout=DOWNLOAD_PER_ATTEMPT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        local_url = None
        err = f"timeout (>{DOWNLOAD_PER_ATTEMPT_TIMEOUT}s)"
    except Exception as e:
        local_url = None
        err = f"{type(e).__name__}: {e}"
    download_ms = int((datetime.now() - download_start).total_seconds() * 1000)

    if local_url:
        # 成功
        try:
            postprocess = await maybe_trim_generated_face_grid_prefix(
                ai_tool_id=ai_tool_id,
                result_url=local_url,
                media_type=media_type,
            )
            final_url = postprocess.result_url
            AIToolsModel.update_by_project_id_with_cdn_sync(
                project_id=project_id,
                result_url=final_url,
                status=AI_TOOL_STATUS_COMPLETED,
                completed_time=datetime.now(),
            )
            DownloadQueueModel.mark_success(row_id, final_url)
            # 标记当前实现方尝试成功（原 _handle_task_success 终态处理一并挪到 worker）
            try:
                from model.implementation_attempts import ImplementationAttemptModel, ATTEMPT_STATUS_SUCCESS
                ImplementationAttemptModel.mark_active_attempt_completed(task_id, ATTEMPT_STATUS_SUCCESS)
            except Exception as ae:
                logger.warning(f"mark attempt success failed task={task_id}: {ae}")
            _log(task_id, AIToolsLogEvent.DOWNLOAD_COMPLETED, project_id=project_id,
                 message="下载/缓存完成", duration_ms=download_ms,
                 detail={'source_url': remote_url, 'final_url': final_url, 'queue_wait_ms': queue_wait_ms})
            _log(task_id, AIToolsLogEvent.TASK_COMPLETED, project_id=project_id,
                 status_to=AI_TOOL_STATUS_COMPLETED, message="任务完成（下载队列）",
                 detail={'result_url': final_url})
            logger.info(f"download_queue id={row_id} ai_tool={ai_tool_id} OK: {remote_url} -> {final_url} "
                        f"({download_ms}ms, queue_wait={queue_wait_ms}ms)")
        except Exception as e:
            # 更新 ai_tools 失败：保留 status=processing，租约过期后由下个 tick 回收重试
            logger.error(f"download_queue id={row_id} success-but-update-failed: {e}")
    else:
        # 失败：重试或兜底
        next_try = try_count + 1
        if next_try < max_try:
            backoff = _backoff_seconds(try_count)
            next_trigger = datetime.now() + timedelta(seconds=backoff)
            DownloadQueueModel.reschedule(row_id, next_try, next_trigger, err or "unknown")
            _log(task_id, AIToolsLogEvent.RETRY_SCHEDULED, project_id=project_id,
                 message=f"下载失败，{backoff}s 后重试(第{next_try}/{max_try}次)",
                 detail={'source_url': remote_url, 'error': err, 'next_try': next_try})
            logger.warning(f"download_queue id={row_id} ai_tool={ai_tool_id} FAIL try={try_count}, "
                           f"retry+{backoff}s: {err}")
        else:
            # 达 max_try：用 remote_url 兜底 COMPLETED（H3）
            try:
                AIToolsModel.update_by_project_id_with_cdn_sync(
                    project_id=project_id,
                    result_url=remote_url,
                    status=AI_TOOL_STATUS_COMPLETED,
                    completed_time=datetime.now(),
                )
                DownloadQueueModel.mark_failed(row_id, f"gave up after {max_try} tries: {err}")
                try:
                    from model.implementation_attempts import ImplementationAttemptModel, ATTEMPT_STATUS_SUCCESS
                    ImplementationAttemptModel.mark_active_attempt_completed(task_id, ATTEMPT_STATUS_SUCCESS)
                except Exception as ae:
                    logger.warning(f"mark attempt success failed task={task_id}: {ae}")
                _log(task_id, AIToolsLogEvent.MAX_RETRY_EXCEEDED, project_id=project_id,
                     message=f"下载{max_try}次仍失败，使用原URL兜底",
                     detail={'source_url': remote_url, 'fallback_url': remote_url, 'error': err})
                _log(task_id, AIToolsLogEvent.TASK_COMPLETED, project_id=project_id,
                     status_to=AI_TOOL_STATUS_COMPLETED, message="任务完成（下载兜底原URL）",
                     detail={'result_url': remote_url})
                logger.warning(f"download_queue id={row_id} ai_tool={ai_tool_id} GIVEUP "
                               f"fallback={remote_url} (err={err})")
            except Exception as e:
                logger.error(f"download_queue id={row_id} giveup-but-update-failed: {e}")


async def process_download_queue() -> None:
    """
    消费者入口：每 DOWNLOAD_POLL_INTERVAL 秒由 scheduler 触发。

    while 持续 claim + 并发下载直到队列空，受 DOWNLOAD_MAX_BATCHES_PER_TICK 限制（M2）。
    scheduler 注册时 max_instances=1 + coalesce=True 保证不重叠。
    """
    wid = _worker_id()
    batch = 0
    total = 0
    while batch < DOWNLOAD_MAX_BATCHES_PER_TICK:
        try:
            rows = DownloadQueueModel.claim_pending(
                limit=DOWNLOAD_DISPATCHER_CONCURRENCY,
                lease_seconds=DOWNLOAD_LEASE_SECONDS,
                worker_id=wid,
            )
        except Exception as e:
            logger.error(f"claim_pending failed: {e}")
            break
        if not rows:
            break
        batch += 1
        logger.info(f"download_queue worker={wid} batch={batch} claimed {len(rows)} rows")
        # 整体超时兜底（每个 _process_one 内下载已有 wait_for；此处仅防 gather 永不返回，
        # 真正卡死的行会被下个 tick 的租约回收 P1）
        try:
            await asyncio.wait_for(
                asyncio.gather(*[_process_one(r) for r in rows], return_exceptions=True),
                timeout=(
                    DOWNLOAD_PER_ATTEMPT_TIMEOUT
                    + GeneratedVideoFaceGridTrimConstants.MAX_PROCESSING_SECONDS
                    + DOWNLOAD_COMPLETION_MARGIN_SECONDS
                ),
            )
        except asyncio.TimeoutError:
            logger.warning(f"download_queue worker={wid} batch={batch} gather timeout, "
                           f"stuck rows will be reclaimed by lease")
        total += len(rows)
    if total:
        logger.info(f"download_queue worker={wid} tick done: {total} rows / {batch} batches")
