"""
音频时长探测工具：用 ffprobe 获取音频时长（秒）。

支持两种输入：
- HTTP(S) URL：ffprobe 原生支持网络输入（如 TTS 产出的 result_url）。
- 本地文件路径：直接探测。

设计要点：
- 失败返回 None，不抛 HTTPException（区别于 api/media.py 的版本），便于在非 HTTP 上下文安全调用。
- 同步函数，调用方在异步上下文应通过 asyncio.to_thread 包装，避免阻塞事件循环。
"""
import logging
import os
import subprocess
from typing import Optional

from config.config_util import get_config_path, resolve_bin_path
from config.constant import FFPROBE_AUDIO_DURATION_TIMEOUT
from utils.project_path import get_project_root

logger = logging.getLogger(__name__)


def _get_ffprobe_path() -> str:
    """从主配置文件读取 ffprobe 路径（与 api/media.py 一致）。"""
    try:
        config_file = get_config_path()
        config_path = os.path.join(get_project_root(), config_file)
        if os.path.exists(config_path):
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            ffprobe = (config.get("bin") or {}).get("ffprobe", "ffprobe")
            return resolve_bin_path(ffprobe, get_project_root())
    except Exception as e:
        logger.warning(f"读取 ffprobe 配置失败，使用默认值 ffprobe: {e}")
    return "ffprobe"


def get_audio_duration_seconds(url_or_path: str) -> Optional[float]:
    """
    用 ffprobe 获取音频时长（秒）。

    Args:
        url_or_path: HTTP(S) URL 或本地文件路径。

    Returns:
        时长（秒，float）；失败（找不到文件/超时/解析失败）返回 None。
    """
    if not url_or_path:
        return None

    ffprobe_path = _get_ffprobe_path()
    # -headers 用于 HTTP 源；对本地文件无副作用。
    cmd = [
        ffprobe_path,
        '-v', 'quiet',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        url_or_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=FFPROBE_AUDIO_DURATION_TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        logger.warning(
            f"ffprobe 无法获取音频时长: {url_or_path} "
            f"returncode={result.returncode} stderr={result.stderr.strip()}"
        )
        return None
    except subprocess.TimeoutExpired:
        logger.warning(f"ffprobe 执行超时({FFPROBE_AUDIO_DURATION_TIMEOUT}s): {url_or_path}")
        return None
    except FileNotFoundError:
        logger.error(f"找不到 ffprobe: {ffprobe_path}，请检查配置文件中 bin.ffprobe 路径")
        return None
    except ValueError:
        logger.warning(f"ffprobe 输出无法解析为时长: {result.stdout!r} for {url_or_path}")
        return None
    except Exception as e:
        logger.warning(f"ffprobe 探测音频时长出现非预期错误: {url_or_path} - {e}")
        return None


async def probe_audio_duration(url_or_path: str) -> Optional[float]:
    """
    异步包装：在线程池中探测音频时长，避免阻塞事件循环。

    Args:
        url_or_path: HTTP(S) URL 或本地文件路径。

    Returns:
        时长（秒，float）；失败返回 None。
    """
    import asyncio
    return await asyncio.to_thread(get_audio_duration_seconds, url_or_path)
