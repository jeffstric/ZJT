"""
媒体验证 API 路由
使用 ffprobe 直接获取媒体文件时长，不依赖 jianying 模块
"""
from fastapi import APIRouter, File, Request, UploadFile, Form, HTTPException
import asyncio
import logging
import subprocess
import tempfile
import os
import yaml
from typing import Optional, List

from config.config_util import resolve_bin_path, get_config_path
from config.constant import MediaConstants
from perseids_server.utils.permission import require_permission
from utils.media_upload import (
    UploadValidationError,
    resolve_media_extension,
    save_upload_chunked,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_ffprobe_path() -> str:
    """从主配置文件读取 ffprobe 路径"""
    try:
        config_file = get_config_path()
        config_path = os.path.join(PROJECT_ROOT, config_file)
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            ffprobe = (config.get("bin") or {}).get("ffprobe", "ffprobe")
            return resolve_bin_path(ffprobe, PROJECT_ROOT)
    except Exception as e:
        logger.warning(f"读取 ffprobe 配置失败，使用默认值: {e}")
    return "ffprobe"


def _get_media_duration_seconds(file_path: str) -> float:
    """
    使用 ffprobe 获取媒体文件时长（秒）

    Args:
        file_path: 媒体文件路径

    Returns:
        时长（秒）

    Raises:
        HTTPException: ffprobe 执行失败时
    """
    ffprobe_path = _get_ffprobe_path()
    cmd = [
        ffprobe_path,
        '-v', 'quiet',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        else:
            raise HTTPException(
                status_code=400,
                detail=f"ffprobe 无法获取文件时长: {result.stderr.strip() or '未知错误'}"
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=400, detail="ffprobe 执行超时")
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"找不到 ffprobe: {ffprobe_path}，请检查配置文件中 bin.ffprobe 路径"
        )
    except ValueError:
        raise HTTPException(status_code=400, detail=f"ffprobe 输出无法解析: {result.stdout}")


async def _save_upload_files(files: List[UploadFile]) -> tuple:
    """
    将上传文件保存到临时目录，返回 (临时文件路径列表, 总时长)

    Returns:
        (temp_file_paths, total_duration_seconds)
    """
    temp_files = []
    total_duration = 0.0

    try:
        for f in files:
            # 安全校验：扩展名白名单 + 魔数校验 + 分块大小上限（音频 50MB / 视频 200MB），
            # 分块读取同时消除整文件读入内存的原语
            # （docs/security/upload_security.md 统一接入方式）
            ext = resolve_media_extension(f.filename or '')
            fd, tmp_name = tempfile.mkstemp(suffix=ext)
            os.close(fd)
            temp_files.append(tmp_name)
            await asyncio.to_thread(save_upload_chunked, f, tmp_name, ext)

            duration = _get_media_duration_seconds(temp_files[-1])
            total_duration += duration
    except BaseException:
        # 任何失败（校验失败/写盘失败/ffprobe 失败）都要清理已落盘的临时文件，
        # 否则 /tmp 会被失败请求永久撑满磁盘
        _cleanup_temp_files(temp_files)
        raise

    return temp_files, total_duration


def _cleanup_temp_files(temp_files: List[str]):
    """清理临时文件"""
    for tmp_file in temp_files:
        try:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
        except Exception as e:
            logger.warning(f"Failed to remove temp file {tmp_file}: {e}")


def _resolve_url_to_local_path(url: str) -> Optional[str]:
    """将 /upload/... URL 转换为本地文件路径"""
    try:
        from urllib.parse import urlparse
        upload_dir = os.path.join(PROJECT_ROOT, "upload")

        if url.startswith("/upload/"):
            relative_path = url[8:]
        elif "/upload/" in url:
            parsed = urlparse(url)
            relative_path = parsed.path[8:] if parsed.path.startswith("/upload/") else None
        else:
            return None

        if not relative_path:
            return None
        # 拒绝路径穿越：仅允许 upload 目录内的相对子路径，并以 realpath 收敛，
        # 防止把 ffprobe 变成本地文件存在性探测 oracle
        if "\\" in relative_path:
            return None
        parts = relative_path.split("/")
        if any(p in ("", ".", "..") for p in parts):
            return None
        local_path = os.path.join(upload_dir, *parts)
        local_path = os.path.realpath(local_path)
        upload_real = os.path.realpath(upload_dir)
        if os.path.commonpath([local_path, upload_real]) != upload_real:
            return None
        return local_path if os.path.exists(local_path) else None
    except Exception:
        return None


async def _get_urls_duration(urls_str: str) -> float:
    """从逗号分隔的URL列表中计算总时长"""
    total = 0.0
    urls = [u.strip() for u in urls_str.split(',') if u.strip()]
    for url in urls:
        local_path = _resolve_url_to_local_path(url)
        if local_path:
            total += _get_media_duration_seconds(local_path)
        else:
            logger.warning(f"无法解析媒体URL到本地路径: {url}")
    return total


@router.post("/validate-duration")
@require_permission("media:validate_duration")
async def validate_media_duration(
    request: Request,
    audio_files: List[UploadFile] = File(default=[]),
    video_files: List[UploadFile] = File(default=[]),
    audio_urls: Optional[str] = Form(None, description="逗号分隔的音频URL列表"),
    video_urls: Optional[str] = Form(None, description="逗号分隔的视频URL列表"),
    max_duration_seconds: int = 15
):
    """
    验证上传的音频和视频文件的总时长
    多个音频文件时长累加，多个视频文件时长累加，总和不能超过限制

    参数:
        audio_files: 音频文件列表（可选，支持多个）
        video_files: 视频文件列表（可选，支持多个）
        max_duration_seconds: 最大允许的总时长（秒），默认15秒

    返回:
        {
            "code": 0,
            "data": {
                "audio_duration": 5.0,
                "video_duration": 8.0,
                "total_duration": 13.0,
                "valid": true
            }
        }
    """
    if not audio_files and not video_files and not audio_urls and not video_urls:
        raise HTTPException(
            status_code=400,
            detail="请至少上传一个音频或视频文件"
        )

    if len(audio_files) + len(video_files) > MediaConstants.VALIDATE_DURATION_MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多验证 {MediaConstants.VALIDATE_DURATION_MAX_FILES} 个媒体文件"
        )

    audio_temp = []
    video_temp = []

    try:
        # 处理所有音频文件，累加时长
        audio_duration = 0.0
        if audio_urls:
            audio_duration = await _get_urls_duration(audio_urls)
        elif audio_files:
            audio_temp, audio_duration = await _save_upload_files(audio_files)

        # 处理所有视频文件，累加时长
        video_duration = 0.0
        if video_urls:
            video_duration = await _get_urls_duration(video_urls)
        elif video_files:
            video_temp, video_duration = await _save_upload_files(video_files)

        # 计算总时长
        total_duration = audio_duration + video_duration

        # 音频和视频分别验证：各自不超过限制
        audio_valid = audio_duration <= max_duration_seconds
        video_valid = video_duration <= max_duration_seconds
        is_valid = audio_valid and video_valid

        # 生成错误信息
        error_parts = []
        if not audio_valid:
            error_parts.append(f"音频总时长 {audio_duration:.2f}秒 超过限制 {max_duration_seconds}秒")
        if not video_valid:
            error_parts.append(f"视频总时长 {video_duration:.2f}秒 超过限制 {max_duration_seconds}秒")

        # 清理临时文件
        _cleanup_temp_files(audio_temp + video_temp)

        return {
            "code": 0,
            "data": {
                "audio_duration": round(audio_duration, 2),
                "video_duration": round(video_duration, 2),
                "total_duration": round(total_duration, 2),
                "max_duration": max_duration_seconds,
                "valid": is_valid,
                "message": "；".join(error_parts) if not is_valid else f"时长验证通过：音频 {audio_duration:.2f}秒，视频 {video_duration:.2f}秒"
            }
        }

    except HTTPException:
        _cleanup_temp_files(audio_temp + video_temp)
        raise
    except UploadValidationError as e:
        _cleanup_temp_files(audio_temp + video_temp)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error validating media duration: {e}", exc_info=True)
        _cleanup_temp_files(audio_temp + video_temp)
        raise HTTPException(
            status_code=500,
            detail=f"媒体验证出错: {str(e)}"
        )
