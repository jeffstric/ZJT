# -*- coding: utf-8 -*-
"""视频提取剧本（video_workflow 剧本提取节点）后端服务。

链路：视频 → 关键帧多批收集（复用 extract-frame 的场景检测/翻页语义）
       + 音轨提取 → SenseVoice 分段 ASR（段偏移还原全片时间戳）
       → 关键帧图片（压缩 base64）+ 带时间戳转写稿 → 多模态 VL 模型一次性生成文字剧本。

设计取舍：一次性多模态生成任务，不走 PM/ExpertAgent 重栈（无 ask_user / 工具循环 / SSE），
与 llm/script_parser.py、services/image_describe.py 同为"纯 LLM 提取模块"模式；
模型挑选 / 图片压缩 / LLM 调用复用 services/vl_gateway.py 共享网关。

任务模型：DB 状态表（script_extract_task，跨进程共享）+ asyncio.create_task 在创建
请求的进程内后台执行 + 前端轮询状态接口（链路分钟级耗时，不能像 extract-frame
一样同步返回）。gunicorn 多 worker 部署下 POST 与轮询 GET 可能落在不同进程，
内存注册表会 404；落库后任意 worker 均可查状态，重启也只丢失"进行中"任务
（updated_at 超 TTL 判失联，前端提示重新提取）。全链路异步（ffmpeg 子进程 /
httpx / to_thread），不阻塞事件循环（web 接口红线）；同步 pymysql 调用一律
经 asyncio.to_thread 包装。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from config.constant import (
    MediaConstants as MC,
    VideoScriptExtractConstants as C,
    VL_GATEWAY_CLIENT_INIT_TIMEOUT,
)
from llm.llm_client_factory import get_llm_client
from model.script_extract_task import ScriptExtractTaskModel
from services.video_frame_extract_service import (
    FrameExtractError,
    detect_scene_cut_points,
    extract_frame_at,
    extract_last_frame,
    probe_stream_duration,
)
from services.voice_replace.ffmpeg_util import FfmpegError, extract_audio, slice_audio
from services.voice_replace.asr_driver import get_asr_driver
from services.vl_gateway import pick_vl_model
from utils.image_compressor import compress_local_image_to_base64
from utils.project_path import get_upload_temp_dir

logger = logging.getLogger(__name__)


def _make_stamp() -> str:
    """临时文件命名戳：时间戳 + 短 uuid（与 extract-frame 接口的命名规则一致）。"""
    return f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

# 剧本提取智能体（多模态 VL 一次性生成）的系统提示词
SCRIPT_EXTRACT_SYSTEM_PROMPT = (
    "你是资深影视编剧「剧本提取智能体」。用户会提供一段视频的若干关键帧截图"
    "（按时间顺序标注时间点）和可选的语音转写稿（带时间戳）。"
    "请综合画面与声音信息，还原撰写这部视频的文字剧本。\n"
    "\n"
    "输出要求（中文，Markdown 格式）：\n"
    "1. 第一行用「# 」输出剧本标题。\n"
    "2. 按「场景」组织：每个场景以「## 场景1（时间 00:00-00:35｜地点/环境）」的格式开头"
    "（序号依次为 场景1、场景2、场景3……），时间区间依据关键帧时间点与转写稿时间戳估算。\n"
    "3. 每个场景内依次写：\n"
    "   - 【画面】镜头与画面描述（依据关键帧：环境、人物、动作、氛围）。"
    "若多张关键帧画面高度重复（解说类视频常循环使用同一段背景素材），"
    "如实写明「重复使用同一/相似镜头」并概括其特征，不要虚构画面变化；"
    "画面中出现的醒目文字（片头标题、片尾大字、水印）应照实记录\n"
    "   - 【对白】「角色：台词」逐句列出（依据转写稿，注明说话人无法区分时用「 voice 」占位提示）\n"
    "   - 【旁白】画外音（如有）\n"
    "   - 【音效/配乐】（如有明确线索）\n"
    "4. 转写稿缺失或无声音的段落，依据画面推断叙事；画面与转写稿冲突时以转写稿为准。\n"
    "5. 结尾附「## 角色表」，列出出场角色与一句话简介。\n"
    "只输出剧本本身，不要解释说明，不要用代码块包裹。"
)


class ScriptExtractError(Exception):
    """剧本提取失败（message 面向接口调用方，可直接返回给前端）。"""


# ---------------------------------------------------------------------------
# DB 任务状态表（script_extract_task）：跨进程共享；执行进程内另起 asyncio 后台任务
# ---------------------------------------------------------------------------

# 本进程内后台 pipeline 的强引用集合（防止 asyncio task 被 GC 回收）
_BG_TASKS: Set[asyncio.Task] = set()


async def get_extract_task(task_id: str) -> Optional[Dict[str, Any]]:
    """查询任务状态（任意 worker 均可查到）。记录不存在或 running 超 TTL（执行进程
    失联/服务重启）返回 None，接口侧回 404 提示重新提取。"""
    task = await asyncio.to_thread(ScriptExtractTaskModel.get_by_task_id, str(task_id or ""))
    if task is None or task.is_expired(C.TASK_TTL_SECONDS):
        return None
    return {
        "task_id": task.task_id,
        "user_id": task.user_id,
        "status": task.status,
        "stage": task.stage,
        "progress": dict(task.progress or {}),
        "error": task.error,
        "result": task.result,
    }


async def _update_task(task_id: str, **fields: Any) -> None:
    """更新任务字段到 DB。DB 异常只记日志不打断 pipeline（提取结果优先落库成功，
    状态丢失最多导致前端多轮询几次）。"""
    try:
        await asyncio.to_thread(ScriptExtractTaskModel.update, task_id, **fields)
    except Exception:
        logger.exception("[script-extract] 任务状态落库失败 task=%s", task_id)


# ---------------------------------------------------------------------------
# 纯函数（单测覆盖）
# ---------------------------------------------------------------------------

def build_slice_ranges(duration: float, slice_seconds: float) -> List[Tuple[float, float]]:
    """把 [0, duration] 按 slice_seconds 切成连续区间（末段可短）。"""
    total = max(0.0, float(duration))
    step = max(1.0, float(slice_seconds))
    if total <= 0:
        return []
    ranges: List[Tuple[float, float]] = []
    start = 0.0
    while start < total - 1e-6:
        ranges.append((round(start, 3), round(min(start + step, total), 3)))
        start += step
    return ranges


def merge_asr_slice_results(
    results: List[Tuple[float, List[Tuple[float, float, str]]]],
) -> List[Tuple[float, float, str]]:
    """合并各分段转写结果：(段偏移, [(start,end,text)...]) → 全片时间戳三元组列表。

    按全片起始时间排序；空文本段丢弃。
    """
    merged: List[Tuple[float, float, str]] = []
    for offset, segments in results:
        for start, end, text in segments:
            clean = (text or "").strip()
            if not clean:
                continue
            merged.append((round(offset + float(start), 3), round(offset + float(end), 3), clean))
    merged.sort(key=lambda item: item[0])
    return merged


def format_asr_transcript(segments: List[Tuple[float, float, str]]) -> str:
    """全片时间戳三元组 → 带时间标签的转写稿文本（[MM:SS] 文本 每行一段）。"""
    lines: List[str] = []
    for start, _end, text in segments:
        lines.append(f"[{format_time_label(start)}] {text}")
    return "\n".join(lines)


def format_time_label(seconds: float) -> str:
    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def build_script_llm_messages(
    transcript: str,
    frames: List[dict],
    duration: float,
) -> List[dict]:
    """构造多模态消息：user text（任务说明+转写稿）+ 逐帧（时间标签文本 + 图片）。

    frames: [{"index": 1, "time_label": "00:00", "data_url": "data:image/jpeg;base64,..."}]
    """
    if transcript:
        transcript_block = (
            "以下是这段视频的语音转写稿（[时间] 文本），时间与关键帧时间点同一时间轴：\n"
            f"{transcript}"
        )
    else:
        transcript_block = "（这段视频没有可用的语音转写稿，请依据画面推断叙事与对白。）"
    user_text = (
        f"视频总时长 {format_time_label(duration)}，下面按时间顺序提供 {len(frames)} 个关键帧截图。\n"
        f"{transcript_block}\n"
        "请根据以上信息输出文字剧本。"
    )
    content: List[dict] = [{"type": "text", "text": user_text}]
    for frame in frames:
        content.append({
            "type": "text",
            "text": f"关键帧{frame['index']}（时间点 {frame['time_label']}）",
        })
        content.append({
            "type": "image_url",
            "image_url": {"url": frame["data_url"]},
        })
    return [
        {"role": "system", "content": SCRIPT_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def clean_script_text(content: str) -> str:
    """容错清洗模型回复：去代码块包裹/成对引号包裹/首尾空白，截断到上限。"""
    if not content:
        return ""
    text = str(content).strip()
    stripped = text
    if stripped.startswith("```"):
        # 去掉 ```xxx 开头行与结尾 ``` 行
        first_newline = stripped.find("\n")
        if first_newline != -1 and stripped.endswith("```"):
            stripped = stripped[first_newline + 1:-3].strip()
        elif first_newline != -1:
            stripped = stripped[first_newline + 1:].strip()
    text = stripped
    _QUOTE_PAIRS = ('"\'“「', '"\'”」')
    if len(text) >= 2 and text[0] in _QUOTE_PAIRS[0] and text[-1] == _QUOTE_PAIRS[1][_QUOTE_PAIRS[0].index(text[0])]:
        text = text[1:-1].strip()
    return text[:C.MAX_SCRIPT_CHARS].strip()


# ---------------------------------------------------------------------------
# Pipeline 各阶段
# ---------------------------------------------------------------------------

def frame_budget(frame_height: int) -> Tuple[int, float]:
    """分辨率档位 → (像素上限, 体积上限 MB)。未知档位回退默认 720p 档。"""
    return C.FRAME_BUDGET_BY_HEIGHT.get(
        int(frame_height), C.FRAME_BUDGET_BY_HEIGHT[C.DEFAULT_FRAME_HEIGHT]
    )


def thin_points_by_time(points: List[float], limit: int) -> List[float]:
    """时间点超上限时按序均匀抽稀（保首尾）。"""
    total = len(points)
    if limit <= 0 or total <= limit:
        return list(points)
    if limit == 1:
        return [points[0]]
    idxs = sorted({round(i * (total - 1) / (limit - 1)) for i in range(limit)})
    return [points[i] for i in idxs]


def build_extract_sample_points(
    scene_points: List[float],
    duration: float,
    max_frames: int,
    min_gap: float,
) -> List[float]:
    """采样计划（纯函数）：场景切换点为主、不足 max_frames 时按时间均匀补点，
    合并去重（相邻间隔 ≥ min_gap）后超量抽稀（保首尾）。

    长视频（超过场景检测单次上限）切换点由调用方分段检测合并后传入，
    保证 60 帧级别的采样密度不因时长衰减。"""
    end = max(0.0, float(duration) - 0.05)
    limit = max(1, int(max_frames))
    pts = sorted({min(max(float(p), 0.05), end) for p in scene_points})
    if len(pts) < limit:
        # 均匀补点：在 [0, end] 上取 limit 个等分点（含首尾），与切换点合并
        if limit > 1:
            uniform = [round(end * i / (limit - 1), 2) for i in range(limit)]
        else:
            uniform = [0.0]
        pts = sorted(set(pts) | set(uniform))
    merged: List[float] = []
    for p in pts:
        if not merged or p - merged[-1] >= min_gap:
            merged.append(p)
    return thin_points_by_time(merged, limit)


async def _detect_scene_points_all(video_path: str, duration: float) -> List[float]:
    """全片场景切换检测：超过单次解码上限时长时按段多次检测合并。

    原实现直接跳过超长视频的检测（extract_keyframe_candidates 内单次上限），
    导致长视频翻页采样退化为每批 6 点且首批末点即视频结尾，帧数严重不足
    （实测 871s 视频设 60 帧只拿到 6 帧）。"""
    limit = MC.VIDEO_FRAME_SCENE_DETECT_MAX_DURATION_SECONDS
    points: List[float] = []
    start = 0.0
    while start < duration - 0.1:
        try:
            pts = await detect_scene_cut_points(
                video_path, start_time=start if start > 0 else 0.0,
            )
        except FrameExtractError:
            pts = []
        points.extend(pts)
        start += limit
    return sorted(set(round(p, 3) for p in points))


async def _collect_keyframes(
    video_path: str,
    temp_dir: str,
    stamp: str,
    duration: float,
    max_frames: int,
) -> List[dict]:
    """按采样计划逐点提取关键帧：全片场景检测（分段）+ 均匀补点，共 max_frames 上限。"""
    prefix = f"scriptframe_{stamp}"
    scene_points = await _detect_scene_points_all(video_path, duration)
    points = build_extract_sample_points(
        scene_points, duration, max_frames, MC.VIDEO_FRAME_MIN_POINT_GAP_SECONDS,
    )
    if not points:
        raise ScriptExtractError("未能从视频中提取到关键帧，视频可能无法解码")
    frames: List[dict] = []
    for i, t in enumerate(points):
        image_path = os.path.join(temp_dir, f"{prefix}_{i:03d}.jpg")
        if i == len(points) - 1 and t >= duration - 0.5:
            # 尾点走尾帧链：流时长元数据虚高时 -ss 定位可能落在最后一帧之后
            await extract_last_frame(video_path, image_path)
        else:
            await extract_frame_at(video_path, image_path, t)
        frames.append({"path": image_path, "time_sec": t})
    return frames


async def _extract_audio_track(video_path: str, temp_dir: str, stamp: str) -> Optional[str]:
    """提取音轨为 wav；无音轨/提取失败返回 None（画面推断继续，不强依赖声音）。"""
    wav_path = os.path.join(temp_dir, f"scriptaudio_{stamp}.wav")
    try:
        await extract_audio(video_path, wav_path)
        return wav_path
    except FfmpegError as exc:
        logger.info("[script-extract] 无可用音轨，跳过 ASR: %s", exc)
        return None


async def _transcribe_one_slice(
    driver: Any,
    sem: asyncio.Semaphore,
    wav_path: str,
    temp_dir: str,
    idx: int,
    offset: float,
    stamp: str,
) -> Tuple[float, List[Tuple[float, float, str]]]:
    slice_path = os.path.join(temp_dir, f"asr{idx:03d}_{stamp}.wav")
    await slice_audio(wav_path, slice_path, offset, offset + C.ASR_SLICE_SECONDS)
    try:
        async with sem:
            segments = await driver.transcribe_segments(slice_path, language="auto")
    finally:
        try:
            os.remove(slice_path)
        except OSError:
            pass
    return offset, [(seg.start, seg.end, seg.text) for seg in segments]


async def _transcribe_audio(
    wav_path: str,
    duration: float,
    temp_dir: str,
    task_id: str,
    stamp: str,
) -> str:
    """分段转写整段音轨并合并为带时间戳的转写稿；单段失败跳过（部分可用）。"""
    ranges = build_slice_ranges(duration, C.ASR_SLICE_SECONDS)
    driver = get_asr_driver()
    sem = asyncio.Semaphore(C.ASR_CONCURRENCY)
    total = len(ranges)
    done = 0

    async def _run_one(idx: int, offset: float):
        nonlocal done
        result = await _transcribe_one_slice(driver, sem, wav_path, temp_dir, idx, offset, stamp)
        done += 1
        await _update_task(task_id, progress={"asr_done": done, "asr_total": total})
        return result

    tasks = [_run_one(idx, offset) for idx, (offset, _end) in enumerate(ranges)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    ok_results: List[Tuple[float, List[Tuple[float, float, str]]]] = []
    failed = 0
    for item in results:
        if isinstance(item, BaseException):
            failed += 1
            logger.warning("[script-extract] ASR 分段失败: %s", item)
            continue
        ok_results.append(item)
    if failed:
        logger.warning("[script-extract] ASR 分段失败 %s/%s", failed, total)
    if not ok_results:
        return ""
    return format_asr_transcript(merge_asr_slice_results(ok_results))


async def _compress_frame(path: str, max_pixels: int, max_mb: float) -> Tuple[bool, Optional[str], Optional[str]]:
    return await asyncio.wait_for(
        asyncio.to_thread(
            compress_local_image_to_base64,
            path,
            max_mb,
            max_pixels,
        ),
        timeout=C.FRAME_COMPRESS_TIMEOUT,
    )


async def _generate_script(
    transcript: str,
    frames: List[dict],
    duration: float,
    auth_token: Optional[str],
    frame_height: int = C.DEFAULT_FRAME_HEIGHT,
    model: Optional[str] = None,
    vendor_id: Optional[int] = None,
    model_id: Optional[int] = None,
) -> Tuple[str, str, Optional[int]]:
    """多模态生成剧本。返回 (script, model, vendor_id)。

    model/vendor_id 为用户在节点上指定的提取模型；空则按 VL 偏好挑选
    （pick_vl_model：指定 model 精确匹配 > 偏好 vendor+model > 列表序）。
    """
    picked = await pick_vl_model(
        C.PREFERRED_VENDOR, C.PREFERRED_MODEL, model=model, vendor_id=vendor_id,
    )
    if not picked:
        raise ScriptExtractError("未配置可用的视觉模型，无法生成剧本")
    use_model = model or picked.get("name")
    use_vendor_id = vendor_id if vendor_id is not None else picked.get("vendor_id")
    use_model_id = model_id if model_id is not None else picked.get("model_id")

    budget_pixels, budget_mb = frame_budget(frame_height)
    frame_notes: List[dict] = []
    for i, frame in enumerate(frames, start=1):
        ok, data_url, err = await _compress_frame(frame["path"], budget_pixels, budget_mb)
        if not ok or not data_url:
            logger.warning("[script-extract] 帧压缩失败 %s: %s", frame["path"], err)
            continue
        frame_notes.append({
            "index": i,
            "time_label": format_time_label(frame["time_sec"]),
            "data_url": data_url,
        })
    if not frame_notes:
        raise ScriptExtractError("关键帧图片处理失败")

    messages = build_script_llm_messages(transcript, frame_notes, duration)

    try:
        client = await asyncio.wait_for(
            asyncio.to_thread(get_llm_client, use_model, use_vendor_id),
            timeout=VL_GATEWAY_CLIENT_INIT_TIMEOUT,
        )
    except asyncio.TimeoutError as exc:
        raise ScriptExtractError("视觉模型客户端初始化超时") from exc

    call_kwargs: Dict[str, Any] = dict(
        model=use_model,
        messages=messages,
        temperature=C.LLM_TEMPERATURE,
        max_tokens=C.LLM_MAX_TOKENS,
        auth_token=auth_token or None,
        vendor_id=use_vendor_id,
        model_id=use_model_id,
    )
    if "request_timeout" in inspect.signature(client.call_api).parameters:
        call_kwargs["request_timeout"] = C.LLM_TIMEOUT
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(client.call_api, **call_kwargs),
            timeout=C.LLM_TIMEOUT + 15,
        )
    except asyncio.TimeoutError as exc:
        raise ScriptExtractError("剧本生成超时，请稍后重试") from exc
    except Exception as exc:
        logger.exception("[script-extract] LLM 调用失败 (model=%s)", use_model)
        raise ScriptExtractError(f"剧本生成失败：{exc}") from exc

    content = ""
    try:
        if response and response.choices:
            content = response.choices[0].message.content or ""
    except Exception:
        content = ""
    script = clean_script_text(content)
    if not script:
        raise ScriptExtractError("视觉模型返回内容为空，无法生成剧本")
    return script, str(use_model), use_vendor_id


def _cleanup_files(paths: List[Optional[str]]) -> None:
    for path in paths:
        if not path:
            continue
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 任务入口
# ---------------------------------------------------------------------------

async def _run_extract_task(
    task_id: str,
    video_path: str,
    auth_token: Optional[str],
    max_frames: int,
    frame_height: int,
    model: Optional[str] = None,
    model_id: Optional[int] = None,
    vendor_id: Optional[int] = None,
) -> None:
    temp_dir = get_upload_temp_dir()
    stamp = _make_stamp()
    wav_path: Optional[str] = None
    frame_paths: List[str] = []
    try:
        # 阶段 1：时长校验 + 关键帧收集
        await _update_task(task_id, stage=C.STAGE_FRAMES)
        duration = await probe_stream_duration(video_path)
        if duration is None or duration <= 0:
            raise ScriptExtractError("无法读取视频时长，请确认视频文件有效")
        if duration > C.MAX_VIDEO_DURATION_SECONDS:
            raise ScriptExtractError(
                f"视频时长 {format_time_label(duration)} 超过上限 "
                f"{format_time_label(C.MAX_VIDEO_DURATION_SECONDS)}，请先剪辑"
            )
        frames = await _collect_keyframes(video_path, temp_dir, stamp, duration, max_frames)
        frame_paths = [f["path"] for f in frames]

        # 阶段 2：音轨提取
        await _update_task(task_id, stage=C.STAGE_AUDIO)
        wav_path = await _extract_audio_track(video_path, temp_dir, stamp)

        # 阶段 3：分段 ASR
        transcript = ""
        if wav_path:
            await _update_task(task_id, stage=C.STAGE_ASR, progress={
                "asr_done": 0,
                "asr_total": len(build_slice_ranges(duration, C.ASR_SLICE_SECONDS)),
            })
            transcript = await _transcribe_audio(wav_path, duration, temp_dir, task_id, stamp)

        # 阶段 4：多模态 LLM 生成剧本
        await _update_task(task_id, stage=C.STAGE_LLM)
        script, used_model, used_vendor_id = await _generate_script(
            transcript, frames, duration, auth_token, frame_height,
            model=model, vendor_id=vendor_id, model_id=model_id,
        )

        await _update_task(task_id, status="success", stage=C.STAGE_DONE, error=None, result={
            "script": script,
            "meta": {
                "duration_sec": round(duration, 2),
                "duration_label": format_time_label(duration),
                "frame_count": len(frames),
                "transcript_available": bool(transcript),
                "transcript_chars": len(transcript),
                "model": used_model,
                "vendor_id": used_vendor_id,
            },
        })
        logger.info(
            "[script-extract] 任务完成 task=%s duration=%.1fs frames=%s transcript=%s model=%s",
            task_id, duration, len(frames), len(transcript), used_model,
        )
    except ScriptExtractError as exc:
        logger.warning("[script-extract] 任务失败 task=%s: %s", task_id, exc)
        await _update_task(task_id, status="failed", error=str(exc))
    except FrameExtractError as exc:
        logger.warning("[script-extract] 任务失败(帧提取) task=%s: %s", task_id, exc)
        await _update_task(task_id, status="failed", error=str(exc))
    except asyncio.CancelledError:
        await _update_task(task_id, status="failed", error="任务已取消")
        raise
    except Exception as exc:
        logger.exception("[script-extract] 任务异常 task=%s", task_id)
        await _update_task(task_id, status="failed", error=f"剧本提取失败：{exc}")
    finally:
        await _update_task(task_id, stage=C.STAGE_DONE)
        _cleanup_files(frame_paths + [wav_path])


async def create_extract_task(
    video_path: str,
    user_id: Optional[int],
    auth_token: Optional[str],
    max_frames: int = C.DEFAULT_MAX_FRAMES,
    frame_height: int = C.DEFAULT_FRAME_HEIGHT,
    model: Optional[str] = None,
    model_id: Optional[int] = None,
    vendor_id: Optional[int] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """创建提取任务。返回 (task_id, None) 或 (None, error)。

    max_frames / frame_height / model 为节点参数（用户可调），
    调用方需先做边界校验。任务状态落 script_extract_task 表（跨进程共享），
    每用户同时只允许 1 个活跃任务（防重复提交刷 LLM 算力）；执行进程失联
    （updated_at 超 TTL）的 running 记录判失效并释放占用。"""
    if user_id is None:
        return None, "未获取到登录身份，请重新登录"

    # 先把该用户失联的 running 记录标记失败（执行 worker 重启/崩溃场景）
    await asyncio.to_thread(
        ScriptExtractTaskModel.mark_stale_running_failed,
        user_id, C.TASK_TTL_SECONDS, "执行进程已失联，请重新提取",
    )
    running = await asyncio.to_thread(
        ScriptExtractTaskModel.get_running_by_user, user_id, C.TASK_TTL_SECONDS
    )
    if running is not None:
        return None, "已有剧本提取任务进行中，请等待完成后再试"

    task_id = uuid.uuid4().hex
    await asyncio.to_thread(ScriptExtractTaskModel.create, task_id, int(user_id), C.STAGE_FRAMES)

    # 惰性清理过期记录（含失联 running），防表膨胀；失败不影响任务创建
    try:
        await asyncio.to_thread(ScriptExtractTaskModel.cleanup_expired, C.TASK_TTL_SECONDS)
    except Exception:
        logger.exception("[script-extract] 过期任务清理失败")

    bg_task = asyncio.create_task(
        _run_extract_task(
            task_id, video_path, auth_token, max_frames, frame_height,
            model=model, model_id=model_id, vendor_id=vendor_id,
        )
    )
    _BG_TASKS.add(bg_task)
    bg_task.add_done_callback(_BG_TASKS.discard)
    logger.info("[script-extract] 任务创建 task=%s user=%s video=%s", task_id, user_id, video_path)
    return task_id, None
