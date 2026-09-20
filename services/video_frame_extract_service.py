"""video_workflow 提取帧节点的 ffmpeg 后端（POST /api/video-workflow/extract-frame）。

支持四种帧类型：
- first:    首帧
- last:     尾帧（两级回退；修复音轨长于视频轨时 "-sseof -0.1" 定位到最后一帧之后
            导致 "Output file is empty" 的历史缺陷）
- custom:   自定义时间点（time_sec；input-seek 快路径 + select 滤镜全解码兜底）
- keyframes: 关键帧候选批量提取（场景切换检测 + 单镜头均匀采样兜底，上限抽稀）

全部 ffmpeg/ffprobe 经 asyncio.create_subprocess_exec + asyncio.wait_for 执行，
超时后 kill 子进程，不阻塞事件循环（web 接口红线）。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import List, Optional, Sequence, Tuple

from PIL import Image

from config.config_util import get_config_value, resolve_bin_path
from config.constant import MediaConstants as C
from utils.project_path import get_project_root

logger = logging.getLogger(__name__)

# showinfo 输出（stderr）中每选中帧一行的 pts_time 字段
_PTS_TIME_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


class FrameExtractError(Exception):
    """帧提取失败（message 面向接口调用方，可直接返回给前端）。"""


def get_ffmpeg_path() -> str:
    try:
        raw = get_config_value("bin", "ffmpeg", default="ffmpeg")
        return resolve_bin_path(raw, get_project_root())
    except Exception as exc:
        logger.warning("[extract-frame] ffmpeg path fallback: %s", exc)
        return "ffmpeg"


def get_ffprobe_path() -> str:
    try:
        raw = get_config_value("bin", "ffprobe", default="ffprobe")
        return resolve_bin_path(raw, get_project_root())
    except Exception as exc:
        logger.warning("[extract-frame] ffprobe path fallback: %s", exc)
        return "ffprobe"


def _default_timeout() -> float:
    try:
        return float(get_config_value("bin", "ffmpeg_timeout", default=30))
    except Exception:
        return 30.0


def _fallback_timeout(timeout: Optional[float]) -> float:
    return float(timeout if timeout is not None else C.VIDEO_FRAME_FALLBACK_TIMEOUT_SECONDS)


async def _run_bin(cmd: Sequence[str], timeout: float) -> Tuple[int, bytes, bytes]:
    """执行外部命令并等待退出，返回 (returncode, stdout, stderr)；超时 kill。
    （必须返回 communicate() 的结果：流在 communicate 后已耗尽，proc.stdout 不可再读。）"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise FrameExtractError(f"ffmpeg 超时({timeout}s): {os.path.basename(cmd[0])}") from exc
    except FileNotFoundError as exc:
        raise FrameExtractError(f"未找到可执行文件: {cmd[0]}") from exc
    return proc.returncode, stdout or b"", stderr or b""


async def _ffmpeg_ok(args: Sequence[str], timeout: float) -> bool:
    """跑一条 ffmpeg 命令，returncode==0 即成功（stderr 细节仅记日志）。"""
    cmd = [get_ffmpeg_path(), *args]
    logger.info("[extract-frame][ffmpeg] %s", " ".join(cmd[:8]))
    returncode, _stdout, stderr = await _run_bin(cmd, timeout)
    if returncode != 0:
        logger.warning("[extract-frame] ffmpeg exit %s: %s", returncode, stderr.decode(errors="replace")[-600:])
    return returncode == 0


def _validate_image_file(path: str) -> bool:
    """输出文件存在、非空、且为可解码图片（拦截写了一半的损坏输出）。"""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        logger.warning("[extract-frame] 输出图片校验失败: %s", path)
        return False


async def probe_stream_duration(video_path: str, timeout: Optional[float] = None) -> Optional[float]:
    """视频流时长（秒）。比容器 format duration 更准：音轨长于视频轨时容器时长取最长流，
    用它定位尾帧/校验时间点会越界。取不到时回退 format duration，再取不到返回 None。"""
    timeout = float(timeout if timeout is not None else _default_timeout())

    async def _probe(entries: str) -> Optional[float]:
        cmd = [
            get_ffprobe_path(),
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", entries,
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        try:
            returncode, stdout, _stderr = await _run_bin(cmd, timeout)
        except FrameExtractError:
            return None
        if returncode != 0 or not stdout.strip():
            return None
        try:
            value = float(stdout.decode(errors="replace").strip().splitlines()[-1])
            return value if value > 0 else None
        except (ValueError, IndexError):
            return None

    stream_dur = await _probe("stream=duration")
    if stream_dur is not None:
        return stream_dur
    return await _probe("format=duration")


async def extract_first_frame(video_path: str, image_path: str, timeout: Optional[float] = None) -> None:
    timeout = float(timeout if timeout is not None else _default_timeout())
    ok = await _ffmpeg_ok(["-i", video_path, "-frames:v", "1", "-q:v", "2", "-y", image_path], timeout)
    if not ok or not _validate_image_file(image_path):
        raise FrameExtractError("首帧提取失败，视频可能无法解码")


async def extract_last_frame(video_path: str, image_path: str, timeout: Optional[float] = None) -> None:
    """两级尾帧提取。

    快路径: -sseof -<窗口> -update 1 —— 解码尾部窗口全部帧并覆盖写同一文件，
    留下的即真正的最后一帧。不能带 -frames:v 1（会在窗口第一帧后停止）。
    兜底:   全片 -update 1（窗口仍空输出时，例如流时长元数据虚高幅度大于窗口）。
    """
    timeout = float(timeout if timeout is not None else _default_timeout())
    window = C.VIDEO_FRAME_TAIL_SEEK_WINDOW_SECONDS
    ok = await _ffmpeg_ok(
        ["-sseof", f"-{window}", "-i", video_path, "-update", "1", "-q:v", "2", "-y", image_path],
        timeout,
    )
    if ok and _validate_image_file(image_path):
        return
    logger.warning("[extract-frame] 尾帧快路径空输出，降级全片解码: %s", video_path)
    ok = await _ffmpeg_ok(
        ["-i", video_path, "-update", "1", "-q:v", "2", "-y", image_path],
        _fallback_timeout(timeout),
    )
    if not ok or not _validate_image_file(image_path):
        raise FrameExtractError("尾帧提取失败，视频可能无法解码")


async def extract_frame_at(
    video_path: str,
    image_path: str,
    time_sec: float,
    timeout: Optional[float] = None,
) -> None:
    """提取 time_sec 时刻的第一帧。两级：input-seek 快路径 → select 滤镜全解码兜底
    （实证：-ss 接近视频流末尾时 demuxer seek 可能落在最后一帧之后，快路径 0 帧）。"""
    timeout = float(timeout if timeout is not None else _default_timeout())
    t = max(0.0, float(time_sec))
    ok = await _ffmpeg_ok(
        ["-ss", f"{t:.3f}", "-i", video_path, "-frames:v", "1", "-update", "1", "-q:v", "2", "-y", image_path],
        timeout,
    )
    if ok and _validate_image_file(image_path):
        return
    logger.warning("[extract-frame] 时间点 %.3fs 快路径空输出，降级 select 全解码: %s", t, video_path)
    ok = await _ffmpeg_ok(
        ["-i", video_path, "-vf", f"select='gte(t,{t:.3f})'", "-frames:v", "1", "-q:v", "2", "-y", image_path],
        _fallback_timeout(timeout),
    )
    if not ok or not _validate_image_file(image_path):
        raise FrameExtractError(f"时间点 {t:.2f}s 之后没有可解码的视频帧")


async def detect_scene_cut_points(
    video_path: str,
    threshold: Optional[float] = None,
    timeout: Optional[float] = None,
    start_time: float = 0.0,
) -> List[float]:
    """场景切换检测：返回切换点时间戳列表（秒，绝对时间）。

    start_time > 0 时用 input seek 只解码该点之后的内容（时间戳被重置为相对
    起点，实测 showinfo 输出为相对值），结果统一加回偏移换算为绝对时间。
    调用方须先做剩余时长上限判断。"""
    timeout = float(timeout if timeout is not None else _default_timeout())
    th = float(threshold if threshold is not None else C.VIDEO_FRAME_SCENE_THRESHOLD)
    start = max(0.0, float(start_time))
    cmd = [
        get_ffmpeg_path(),
    ]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += [
        "-i", video_path,
        "-vf", f"select='gt(scene,{th})',showinfo",
        "-f", "null", "-",
    ]
    logger.info("[extract-frame][scene-detect] %s", " ".join(cmd[:6]))
    try:
        returncode, _stdout, stderr = await _run_bin(cmd, _fallback_timeout(timeout))
    except FrameExtractError as exc:
        logger.warning("[extract-frame] 场景检测失败，按单镜头处理: %s", exc)
        return []
    if returncode != 0:
        logger.warning("[extract-frame] 场景检测 exit %s: %s", returncode, stderr.decode(errors="replace")[-600:])
        return []
    # -ss 跳段后 pts_time 为相对起点的时间，加回 start 得到绝对时间
    return [start + float(m) for m in _PTS_TIME_RE.findall(stderr.decode(errors="replace"))]


def build_keyframe_points(
    duration: float,
    scene_points: Sequence[float],
    start_time: float = 0.0,
) -> List[float]:
    """候选时间点集合（纯函数，便于单测）。翻页语义：每批最多 limit 个。

    - 首批（start_time == 0）：首帧 + 起点之后最早的 (limit-1) 个切换点；
      切换点已取尽时补尾帧。
    - 续批（start_time > 0）：起点之后最早的 limit 个切换点（严格晚于起点，
      避免与上一批末帧重复）；切换点取尽时补尾帧，让最后一批自然收在视频结尾。
    - 剩余段无切换点（单镜头）：在 (start, 尾帧] 内均匀采样一批（含尾帧）。
    - 段内已无可取点时返回 []（已到视频末尾）。
    """
    eps = 0.05
    gap = C.VIDEO_FRAME_MIN_POINT_GAP_SECONDS
    limit = C.VIDEO_FRAME_KEYFRAME_MAX_COUNT
    end = max(0.0, float(duration) - eps)
    start = min(max(0.0, float(start_time)), end)
    resumed = start > 0
    # 续批时剩余段已不足一个最小间隔：没有新帧可取
    if resumed and end - start < gap:
        return []

    # 界外切换点 clamp 进有效区间（与首尾重合的点由集合去重 + 间隔合并吸收）
    cuts = sorted({min(max(float(p), eps), end) for p in scene_points})
    # 续批时丢弃 start 及其近邻内的切换点（与上一批末帧重复）
    cuts = [p for p in cuts if p - start >= (gap if resumed else 0)]

    if not cuts:
        n = max(2, C.VIDEO_FRAME_KEYFRAME_UNIFORM_SAMPLES)
        if resumed:
            # (start, end] 内均匀取 n 个点（不含 start 本身），末点恰为尾帧
            pts = [round(start + (end - start) * i / n, 3) for i in range(1, n + 1)]
        else:
            pts = [round(end * i / (n - 1), 3) for i in range(n)]
        merged: List[float] = []
        for p in pts:
            if not merged or p - merged[-1] >= gap:
                merged.append(p)
        return merged or [end]

    # 有关键切换点：本批按时间顺序取最早的 quota 个，不跨段抽稀（翻页不漏镜头）
    quota = limit - 1 if not resumed else limit
    taken = cuts[:quota]
    pts = ([0.0] if not resumed else []) + taken
    # 切换点已取尽 → 补尾帧收尾；还有剩余切换点则留给下一批
    if len(taken) == len(cuts) and pts[-1] < end - gap:
        pts.append(end)

    merged = []
    for p in pts:
        if not merged or p - merged[-1] >= gap:
            merged.append(p)
    return merged


async def extract_keyframe_candidates(
    video_path: str,
    output_dir: str,
    name_prefix: str,
    timeout: Optional[float] = None,
    start_time: float = 0.0,
) -> List[dict]:
    """关键帧候选批量提取。返回 [{"path": 绝对路径, "time_sec": 秒}, ...]（不负责 URL 拼接）。

    start_time > 0 时只提取该时刻之后的关键帧（翻页续批），段内无可取点时返回 []。"""
    timeout = float(timeout if timeout is not None else _default_timeout())
    duration = await probe_stream_duration(video_path, timeout=timeout)
    if duration is None or duration <= 0:
        raise FrameExtractError("无法读取视频时长，关键帧提取失败")

    start = max(0.0, float(start_time))
    scene_points: List[float] = []
    if duration - start <= C.VIDEO_FRAME_SCENE_DETECT_MAX_DURATION_SECONDS:
        scene_points = await detect_scene_cut_points(video_path, timeout=timeout, start_time=start)

    points = build_keyframe_points(duration, scene_points, start_time=start)
    frames: List[dict] = []
    for i, t in enumerate(points):
        image_path = os.path.join(output_dir, f"{name_prefix}_{i:03d}.jpg")
        if i == len(points) - 1 and t >= duration - 0.5:
            # 尾点必须走尾帧链：流时长元数据虚高时 -ss/select 都可能定位到最后一帧之后
            await extract_last_frame(video_path, image_path, timeout=timeout)
        else:
            await extract_frame_at(video_path, image_path, t, timeout=timeout)
        frames.append({"path": image_path, "time_sec": t})
    return frames
