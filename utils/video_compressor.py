"""
视频压缩工具
使用 ffmpeg 将视频压缩到指定最长边分辨率，支持异步非阻塞调用

ffmpeg 路径从 config.yaml 的 bin.ffmpeg 读取
"""
import asyncio
import json
import logging
import os
from typing import Optional, Tuple

from config.constant import MediaConstants
from config.config_util import get_config_value, resolve_bin_path
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


async def get_video_info(video_path: str) -> Optional[dict]:
    """
    使用 ffprobe 获取视频的分辨率和时长信息（非阻塞）

    Args:
        video_path: 视频文件路径

    Returns:
        dict: {"width": int, "height": int, "duration": float} 或 None
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

        data = json.loads(stdout.decode(errors="replace"))

        # 查找视频流
        width, height = 0, 0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream.get("width", 0))
                height = int(stream.get("height", 0))
                break

        duration = float(data.get("format", {}).get("duration", 0))

        return {"width": width, "height": height, "duration": duration}

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
