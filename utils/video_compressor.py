"""
视频压缩工具
使用 ffmpeg 将视频压缩到指定最长边分辨率，支持异步非阻塞调用

ffmpeg 路径从 config.yaml 的 bin.ffmpeg 读取
"""
import asyncio
import json
import logging
import os
import subprocess
import tempfile
import uuid
from typing import Optional, Tuple
from urllib.parse import urlparse, unquote

import requests

from config.constant import (
    MediaConstants,
    REFERENCE_VIDEO_DURATION_PROBE_TIMEOUT,
    SEEDANCE_REFERENCE_VIDEO_DOWNLOAD_CONNECT_TIMEOUT,
    SEEDANCE_REFERENCE_VIDEO_DOWNLOAD_READ_TIMEOUT,
    SEEDANCE_REFERENCE_VIDEO_TRANSCODE_TIMEOUT,
)
from config.config_util import get_config_value, resolve_bin_path
from utils.media_mapping_util import extract_local_path_from_url
from utils.project_path import get_project_root

logger = logging.getLogger(__name__)


def _get_ffmpeg_path() -> str:
    """从配置文件读取 ffmpeg 路径"""
    ffmpeg = get_config_value("bin", "ffmpeg", default="ffmpeg")
    return resolve_bin_path(ffmpeg, get_project_root())


def _get_ffprobe_path() -> str:
    """从配置文件读取 ffprobe 路径"""
    ffprobe = get_config_value("bin", "ffprobe", default="ffprobe")
    return resolve_bin_path(ffprobe, get_project_root())


def _parse_frame_rate(avg_frame_rate: str) -> float:
    """
    解析 ffprobe 的 avg_frame_rate（形如 "120/1"、"30000/1001"、"0/0"）为 float。

    分母为 0 或解析失败时返回 0.0。
    """
    if not avg_frame_rate or "/" not in avg_frame_rate:
        try:
            return float(avg_frame_rate) if avg_frame_rate else 0.0
        except (TypeError, ValueError):
            return 0.0
    try:
        num, den = avg_frame_rate.split("/", 1)
        num_f = float(num)
        den_f = float(den)
        if den_f == 0:
            return 0.0
        return num_f / den_f
    except (TypeError, ValueError):
        return 0.0


async def get_video_info(video_path: str) -> Optional[dict]:
    """
    使用 ffprobe 获取视频的分辨率、时长和帧率信息（非阻塞）

    Args:
        video_path: 视频文件路径

    Returns:
        dict: {"width": int, "height": int, "duration": float, "fps": float} 或 None
    """
    ffprobe_path = _get_ffprobe_path()
    cmd = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        video_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error("ffprobe 执行超时（30秒），已终止")
            return None

        if proc.returncode != 0:
            logger.error(f"ffprobe 执行失败: {stderr.decode(errors='replace')}")
            return None

        data = json.loads(stdout.decode(errors='replace'))

        # 查找视频流
        width, height, fps = 0, 0, 0.0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream.get("width", 0))
                height = int(stream.get("height", 0))
                fps = _parse_frame_rate(stream.get("avg_frame_rate", "0/0"))
                break

        duration = float(data.get("format", {}).get("duration", 0))

        return {"width": width, "height": height, "duration": duration, "fps": fps}

    except Exception as e:
        logger.error(f"获取视频信息失败: {e}")
        return None


def needs_compression(info: dict, max_shortest_edge: int = 480) -> bool:
    """判断视频是否需要压缩（最短边超过阈值）"""
    if not info:
        return True
    shortest = min(info.get("width", 0), info.get("height", 0))
    return shortest > max_shortest_edge


def is_reference_video_pixel_count_valid(
    info: dict,
    min_pixel_count: int = MediaConstants.VIDEO_REFERENCE_MIN_PIXEL_COUNT,
) -> bool:
    """判断参考视频是否满足下游模型的最低总像素数要求。"""
    if not info:
        return False
    width = int(info.get("width", 0) or 0)
    height = int(info.get("height", 0) or 0)
    if width <= 0 or height <= 0:
        return False
    return width * height >= min_pixel_count


def _get_url_or_path_extension(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    path = unquote(parsed.path if parsed.scheme else value)
    return os.path.splitext(path)[1].lower()


def _resolve_local_video_path(video_url: str, project_root: str) -> tuple[Optional[str], list[str], Optional[str]]:
    cleanup_paths: list[str] = []
    if video_url.startswith(("http://", "https://")):
        local_rel = extract_local_path_from_url(video_url)
        if local_rel:
            candidate = os.path.join(project_root, local_rel)
            if os.path.exists(candidate):
                return candidate, cleanup_paths, None

        suffix = _get_url_or_path_extension(video_url) or ".video"
        temp_path = os.path.join(
            tempfile.gettempdir(),
            f"seedance_reference_source_{uuid.uuid4().hex[:8]}{suffix}",
        )
        try:
            with requests.get(
                video_url,
                stream=True,
                timeout=(
                    SEEDANCE_REFERENCE_VIDEO_DOWNLOAD_CONNECT_TIMEOUT,
                    SEEDANCE_REFERENCE_VIDEO_DOWNLOAD_READ_TIMEOUT,
                ),
            ) as response:
                response.raise_for_status()
                with open(temp_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            cleanup_paths.append(temp_path)
            return temp_path, cleanup_paths, None
        except Exception as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            return None, cleanup_paths, f"下载参考视频失败: {e}"

    candidates = []
    if os.path.isabs(video_url):
        candidates.append(video_url)
    else:
        candidates.append(os.path.join(project_root, video_url))
    if video_url.startswith("/"):
        candidates.append(os.path.join(project_root, video_url.lstrip("/\\")))

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate, cleanup_paths, None
    return None, cleanup_paths, f"参考视频文件不存在: {video_url}"


def transcode_reference_video_to_seedance_mp4(
    input_path: str,
    output_path: str,
    timeout: int = SEEDANCE_REFERENCE_VIDEO_TRANSCODE_TIMEOUT,
    max_fps: int = MediaConstants.VIDEO_REFERENCE_MAX_FPS,
) -> tuple[bool, Optional[str]]:
    """
    将参考视频转成 Seedance 可稳定解析 duration 的 MP4。

    通过 -fpsmax 限制输出最大帧率（只丢帧不补帧），避免高刷屏浏览器产出的
    120fps 等超频视频触发下游 doubao-seedance 的 ≤60fps 上限校验。
    需要 ffmpeg ≥4.3。
    """
    if not os.path.exists(input_path):
        return False, f"输入参考视频不存在: {input_path}"

    ffmpeg_path = _get_ffmpeg_path()
    cmd = [
        ffmpeg_path,
        "-y",
        "-i", input_path,
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        "-fpsmax", str(max_fps),  # 限制最大输出帧率：超频只丢帧，低帧率不补帧
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-shortest",
        output_path,
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"ffmpeg 转码超时（{timeout}秒）"
    except FileNotFoundError:
        return False, f"找不到 ffmpeg: {ffmpeg_path}"
    except Exception as e:
        return False, str(e)

    if proc.returncode != 0:
        return False, f"ffmpeg 转码失败: {proc.stderr[-500:]}"
    if not os.path.exists(output_path):
        return False, "ffmpeg 转码未生成输出文件"
    return True, None


def prepare_seedance_reference_video_sync(
    video_url: str,
    config: Optional[dict] = None,
    project_root: Optional[str] = None,
) -> tuple[bool, Optional[str], Optional[str], list[str]]:
    """
    准备 Seedance 参考视频。

    浏览器 MediaRecorder 产出的 WebM 可能没有容器 duration 元数据，火山 Seedance
    输入适配器会解析失败。因此 WebM/MKV 先转为 H.264/AAC MP4，其余格式原样返回。
    """
    if not video_url:
        return False, None, "参考视频为空", []

    source_ext = _get_url_or_path_extension(video_url)
    if source_ext not in {".webm", ".mkv"}:
        return True, video_url, None, []

    root = project_root or get_project_root()
    local_path, cleanup_paths, error = _resolve_local_video_path(video_url, root)
    if not local_path:
        return False, None, error, cleanup_paths

    output_path = os.path.join(
        tempfile.gettempdir(),
        f"seedance_reference_{uuid.uuid4().hex[:8]}.mp4",
    )
    cleanup_paths.append(output_path)
    success, transcode_error = transcode_reference_video_to_seedance_mp4(local_path, output_path)
    if not success:
        return False, None, transcode_error, cleanup_paths
    return True, output_path, None, cleanup_paths


def _probe_video_duration_seconds_sync(
    video_path: str,
    timeout: int = REFERENCE_VIDEO_DURATION_PROBE_TIMEOUT,
) -> Optional[float]:
    """
    同步 ffprobe 探测单个视频的容器时长（秒）。

    MediaRecorder 产出的 WebM 可能缺容器 duration 元数据，探测结果为 0 时返回 None。
    含子进程调用，异步上下文须 asyncio.to_thread 包装。
    """
    ffprobe_path = _get_ffprobe_path()
    cmd = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        video_path,
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.warning(f"ffprobe 探测视频时长失败({video_path}): {e}")
        return None

    if proc.returncode != 0:
        logger.warning(f"ffprobe 返回非零({video_path}): {(proc.stderr or '')[-200:]}")
        return None

    try:
        data = json.loads(proc.stdout or "")
        duration = float(data.get("format", {}).get("duration", 0) or 0)
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning(f"ffprobe 输出解析失败({video_path})")
        return None
    return duration if duration > 0 else None


def get_reference_videos_total_duration_sync(video_path_csv: Optional[str]) -> Optional[float]:
    """
    探测参考视频总时长（秒），用于视频编辑任务的计费时长。

    video_path_csv: 逗号分隔的本地路径/URL 列表（与 ai_tools.video_path 同格式）。
    同步函数（外部 URL 会触发下载），异步上下文须 asyncio.to_thread 包装。

    Returns:
        总时长（秒）；路径为空、任一视频定位/探测失败时返回 None（调用方回退用户输入时长）。
        已知局限：缺 duration 元数据的 WebM/MKV 返回 None，由调用方回退用户输入时长计费。
    """
    paths = [v.strip() for v in (video_path_csv or "").split(",") if v.strip()]
    if not paths:
        return None

    root = get_project_root()
    total = 0.0
    cleanup_paths: list[str] = []
    try:
        for path in paths:
            local_path, cleanup, error = _resolve_local_video_path(path, root)
            cleanup_paths.extend(cleanup or [])
            if not local_path:
                logger.warning(f"参考视频无法定位，计费时长探测回退: {path} ({error})")
                return None
            duration = _probe_video_duration_seconds_sync(local_path)
            if duration is None:
                logger.warning(f"参考视频时长探测失败，计费时长探测回退: {path}")
                return None
            total += duration
        return total
    finally:
        for path in cleanup_paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


async def compress_video(
    input_path: str,
    output_path: str,
    max_shortest_edge: int = 480,
    crf: int = 28,
    preset: str = "fast",
) -> Tuple[bool, Optional[str]]:
    """
    使用 ffmpeg 将视频压缩到最短边不超过指定分辨率（非阻塞）

    缩放规则：最短边 = max_shortest_edge，长边按比例缩放并对齐偶数
    - 横屏（1280x720）→ 缩放为 854x480（短边 480）
    - 竖屏（720x1280）→ 缩放为 480x854（短边 480）
    - 方形（1000x1000）→ 缩放为 480x480

    Args:
        input_path: 输入视频路径
        output_path: 输出视频路径
        max_shortest_edge: 最短边目标分辨率，默认 480
        crf: H.264 压缩质量 (0-51)，越小质量越高文件越大，默认 28
        preset: 编码速度预设，可选 ultrafast/superfast/veryfast/faster/fast/medium/slow/slower/veryslow

    Returns:
        Tuple[bool, Optional[str]]: (是否成功, 错误信息)
    """
    if not os.path.exists(input_path):
        return False, f"输入文件不存在: {input_path}"

    ffmpeg_path = _get_ffmpeg_path()

    # scale filter: 最短边缩放到 max_shortest_edge，长边按比例，-2 保证偶数对齐
    # 横屏 (w>h): h=max_edge, w按比例; 竖屏 (h>w): w=max_edge, h按比例
    scale_filter = (
        f"scale='if(gte(iw,ih),-2,{max_shortest_edge})'"
        f":'if(gte(iw,ih),{max_shortest_edge},-2)'"
        f",setsar=1"
    )

    cmd = [
        ffmpeg_path,
        "-y",                        # 覆盖输出文件
        "-i", input_path,
        "-vf", scale_filter,
        "-c:v", "libx264",
        "-crf", str(crf),
        "-preset", preset,
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",   # MP4 元数据前置，支持边下边播
        output_path,
    ]

    logger.info(f"开始视频压缩: {input_path} -> {output_path} (最短边 {max_shortest_edge}px)")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False, "ffmpeg 压缩超时（300秒），已终止"

        if proc.returncode != 0:
            error_msg = stderr.decode(errors="replace")
            logger.error(f"ffmpeg 压缩失败 (code={proc.returncode}): {error_msg}")
            return False, f"ffmpeg 执行失败: {error_msg[-500:]}"

        if not os.path.exists(output_path):
            return False, "输出文件未生成"

        output_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        input_size_mb = os.path.getsize(input_path) / (1024 * 1024)
        logger.info(f"视频压缩完成: {input_size_mb:.1f}MB -> {output_size_mb:.1f}MB")

        return True, None

    except FileNotFoundError:
        return False, f"找不到 ffmpeg: {ffmpeg_path}，请检查配置文件中 bin.ffmpeg 路径"
    except Exception as e:
        logger.error(f"视频压缩异常: {e}")
        return False, str(e)
