"""
音频时长探测工具：用 ffprobe 获取音频时长（秒）。

支持两种输入：
- HTTP(S) URL：ffprobe 原生支持网络输入（如 TTS 产出的 result_url）。
- 本地文件路径：直接探测。

设计要点：
- 失败返回 None，不抛 HTTPException（区别于 api/media.py 的版本），便于在非 HTTP 上下文安全调用。
- 同步函数，调用方在异步上下文应通过 asyncio.to_thread 包装，避免阻塞事件循环。

另含 Seedance r2v 参考音频的「总时长预算」准备逻辑：按条数均分配额，
超配额的音频用 ffmpeg 截断到临时文件（不修改原文件），供视频驱动在提交前调用。
"""
import logging
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from config.config_util import get_config_path, resolve_bin_path
from config.constant import (
    FFPROBE_AUDIO_DURATION_TIMEOUT,
    SEEDANCE_R2V_AUDIO_TOTAL_DURATION_SAFETY_MARGIN,
    SEEDANCE_R2V_AUDIO_TRIM_TIMEOUT,
)
from utils.project_path import get_project_root, resolve_upload_url_to_local_path

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
        时长（秒，float）；失败（找不到文件/超时/解析失败）返回 None。
    """
    import asyncio
    return await asyncio.to_thread(get_audio_duration_seconds, url_or_path)


def _get_ffmpeg_path() -> str:
    """从主配置文件读取 ffmpeg 路径（与 _get_ffprobe_path 同源）。"""
    try:
        config_file = get_config_path()
        config_path = os.path.join(get_project_root(), config_file)
        if os.path.exists(config_path):
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            ffmpeg = (config.get("bin") or {}).get("ffmpeg", "ffmpeg")
            return resolve_bin_path(ffmpeg, get_project_root())
    except Exception as e:
        logger.warning(f"读取 ffmpeg 配置失败，使用默认值 ffmpeg: {e}")
    return "ffmpeg"


def _resolve_local_source(url_or_path: str) -> str:
    """URL/相对路径优先解析为本地 upload 文件（探测与截断更快更稳），解析不到则原样返回。"""
    if os.path.exists(url_or_path):
        return url_or_path
    try:
        local = resolve_upload_url_to_local_path(url_or_path)
        if local and os.path.exists(local):
            return local
    except Exception:
        pass
    return url_or_path


def _remove_temp_file(path: str) -> None:
    """best-effort 删除临时文件，失败仅记日志。"""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as e:
        logger.warning(f"删除音频截断临时文件失败: {path} - {e}")


def trim_audio_to_duration(url_or_path: str, max_seconds: float) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    将音频截断到 max_seconds，输出到系统临时文件（不修改原文件）。

    用 -acodec copy 流复制（快且无损），截断点按帧对齐可能略有正偏差，
    调用方需在配额中预留安全余量。

    同步函数，调用方在异步上下文应通过 asyncio.to_thread 包装。

    Args:
        url_or_path: HTTP(S) URL 或本地文件路径。
        max_seconds: 截断目标时长（秒）。

    Returns:
        (success, trimmed_path, error)：成功时 trimmed_path 为临时文件路径，
        调用方负责删除；失败时 trimmed_path 为 None。
    """
    if not url_or_path or max_seconds <= 0:
        return False, None, "max_seconds 必须为正数"

    source = _resolve_local_source(url_or_path)
    ext = os.path.splitext(source.split('?')[0])[1] or ".mp3"
    fd, trimmed_path = tempfile.mkstemp(suffix=ext, prefix="seedance_audio_trim_")
    os.close(fd)

    cmd = [
        _get_ffmpeg_path(),
        '-i', source,
        '-t', f"{max_seconds:.3f}",
        '-acodec', 'copy',
        '-y',
        trimmed_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=SEEDANCE_R2V_AUDIO_TRIM_TIMEOUT,
        )
        if result.returncode == 0 and os.path.exists(trimmed_path) and os.path.getsize(trimmed_path) > 0:
            return True, trimmed_path, None
        error = (result.stderr or '').strip()[-500:] or f"returncode={result.returncode}"
        _remove_temp_file(trimmed_path)
        return False, None, error
    except subprocess.TimeoutExpired:
        _remove_temp_file(trimmed_path)
        return False, None, f"ffmpeg 截断超时({SEEDANCE_R2V_AUDIO_TRIM_TIMEOUT}s)"
    except Exception as e:
        _remove_temp_file(trimmed_path)
        return False, None, f"ffmpeg 截断异常: {e}"


def prepare_reference_audio_budget_sync(
    audio_paths: List[str],
    max_total_seconds: float,
    safety_margin: float = SEEDANCE_R2V_AUDIO_TOTAL_DURATION_SAFETY_MARGIN,
) -> List[Dict[str, Any]]:
    """
    按「均分配额」准备 Seedance r2v 参考音频：每条上限 = (max_total_seconds - safety_margin) / 条数。

    背景：火山 r2v 限制参考音频总时长（2.0 系列 ≤15s、2.5 ≤30s），而角色音色源
    音频上传时裁到 20s（TTS 需要）且可注入多条，驱动提交前需按预算自动截断。
    均分保证多角色场景下每条音色样本都有平等露出机会，且总时长必然不超预算。

    同步函数（ffprobe/ffmpeg 子进程），视频驱动在任务 worker 同步上下文中调用。

    Args:
        audio_paths: 音频 URL/路径列表（顺序即注入顺序）。
        max_total_seconds: 模型允许的音频总时长上限（秒）。
        safety_margin: 总预算安全余量（秒），覆盖流复制截断点的帧对齐偏差。

    Returns:
        与输入顺序一致的列表，每项：
        {"source": 原始输入, "path": 提交用路径（原样或截断临时文件）,
         "cleanup_path": 需调用方清理的临时文件路径或 None,
         "duration": 探测到的时长（秒，探测失败为 None）, "limit_seconds": 均分配额}
    """
    paths = [p for p in (str(a or '').strip() for a in audio_paths) if p]
    results: List[Dict[str, Any]] = []
    if not paths:
        return results

    budget = max(max_total_seconds - safety_margin, 0.0)
    per_limit = budget / len(paths)
    for source in paths:
        local = _resolve_local_source(source)
        duration = get_audio_duration_seconds(local)
        item: Dict[str, Any] = {
            "source": source,
            "path": source,
            "cleanup_path": None,
            "duration": duration,
            "limit_seconds": per_limit,
        }
        if duration is None:
            logger.warning(f"参考音频时长探测失败，原样放行: {source}")
            results.append(item)
            continue
        if duration <= per_limit + 1e-6:
            results.append(item)
            continue
        success, trimmed, error = trim_audio_to_duration(local, per_limit)
        if success and trimmed:
            logger.info(
                f"参考音频 {duration:.2f}s 超出均分配额 {per_limit:.2f}s，已截断: {source}"
            )
            item["path"] = trimmed
            item["cleanup_path"] = trimmed
        else:
            logger.warning(f"参考音频截断失败，原样放行: {source} - {error}")
        results.append(item)
    return results


def cleanup_prepared_reference_audio(items: List[Dict[str, Any]]) -> None:
    """删除 prepare_reference_audio_budget_sync 产生的临时截断文件（幂等，可安全重复调用）。"""
    for item in items or []:
        if not isinstance(item, dict):
            continue
        path = item.get('cleanup_path')
        if not path:
            continue
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"删除音频截断临时文件失败: {path} - {e}")
