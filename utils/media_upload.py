"""
上传媒体文件安全校验模块

防两类攻击（安全审计 P0）：
1. 存储型 XSS：/upload/ 由 StaticFiles 直接对外提供，若放任 .html/.svg
   落盘，会以 text/html 同域返回。本模块用扩展名白名单 + 头部魔数校验
   双重拦截（Content-Type 由客户端任意伪造，不作为可信依据）。
2. 资源滥用：分块读取累计字节数，超上限立即中断并清理半成品文件，
   避免 GB 级上传打满内存/磁盘并触发 CDN 成本。

所有接收用户上传媒体文件的端点（server.py 的 _save_user_asset /
_save_uploaded_image / image-to-video upload-media 等）统一走本模块。
本模块为纯同步实现，供 asyncio.to_thread 在工作线程调用，不阻塞事件循环。
"""
import os
from typing import Optional

from config.constant import MediaUploadSafetyConstants

import logging

logger = logging.getLogger(__name__)


class UploadValidationError(ValueError):
    """上传文件校验失败（扩展名不在白名单 / 魔数不匹配 / 超大小上限）。

    端点层捕获后映射为 HTTP 400，message 面向用户可直接透出。
    """


# 扩展名 -> 头部魔数校验函数（入参为文件前 MAGIC_SCAN_BYTES 字节）。
# RIFF/ftyp 容器（webp/wav/avi/mp4/mov/m4a）的品牌标识在偏移 8/4 处；
# mp3 允许 ID3 头或 MPEG 帧同步（0xFFEx）两种开头。
_MAGIC_CHECKS = {
    '.jpg':  lambda b: b[:3] == b'\xff\xd8\xff',
    '.jpeg': lambda b: b[:3] == b'\xff\xd8\xff',
    '.png':  lambda b: b[:8] == b'\x89PNG\r\n\x1a\n',
    '.gif':  lambda b: b[:6] in (b'GIF87a', b'GIF89a'),
    '.webp': lambda b: len(b) >= 12 and b[:4] == b'RIFF' and b[8:12] == b'WEBP',
    '.bmp':  lambda b: b[:2] == b'BM',
    '.mp4':  lambda b: len(b) >= 8 and b[4:8] == b'ftyp',
    '.mov':  lambda b: len(b) >= 8 and b[4:8] == b'ftyp',
    '.m4a':  lambda b: len(b) >= 8 and b[4:8] == b'ftyp',
    '.webm': lambda b: b[:4] == b'\x1a\x45\xdf\xa3',
    '.mkv':  lambda b: b[:4] == b'\x1a\x45\xdf\xa3',
    '.avi':  lambda b: len(b) >= 12 and b[:4] == b'RIFF' and b[8:12] == b'AVI ',
    '.mp3':  lambda b: b[:3] == b'ID3' or (len(b) >= 2 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0),
    '.aac':  lambda b: len(b) >= 2 and b[0] == 0xFF and b[1] in (0xF1, 0xF9),
    '.wav':  lambda b: len(b) >= 12 and b[:4] == b'RIFF' and b[8:12] == b'WAVE',
    '.ogg':  lambda b: b[:4] == b'OggS',
    '.flac': lambda b: b[:4] == b'fLaC',
}

# 白名单全集（与 _MAGIC_CHECKS 的键保持一致）
_ALLOWED_EXTS = (
    MediaUploadSafetyConstants.IMAGE_EXTS
    + MediaUploadSafetyConstants.VIDEO_EXTS
    + MediaUploadSafetyConstants.AUDIO_EXTS
)


def resolve_media_extension(filename: Optional[str]) -> str:
    """解析上传文件名的扩展名并做白名单校验。

    Args:
        filename: 客户端上报的原始文件名（可能为 None）

    Returns:
        规范化的小写扩展名（含点号，如 ".png"）

    Raises:
        UploadValidationError: 扩展名缺失、不在白名单或命中显式拒绝清单
    """
    ext = os.path.splitext(filename or "")[1].lower()
    if not ext:
        raise UploadValidationError("无法识别文件类型：文件名缺少扩展名")
    if ext in MediaUploadSafetyConstants.BLOCKED_EXTS:
        raise UploadValidationError(f"不允许上传 {ext} 文件（可执行/可渲染文档存在安全风险）")
    if ext not in _ALLOWED_EXTS:
        raise UploadValidationError(
            "不支持的文件格式，仅支持图片（jpg/png/webp/gif/bmp）、"
            "视频（mp4/mov/webm/avi/mkv）、音频（mp3/wav/m4a/aac/ogg/flac）"
        )
    return ext


def max_upload_size_for_ext(ext: str) -> int:
    """按扩展名所属媒体类别返回大小上限（字节）。"""
    if ext in MediaUploadSafetyConstants.IMAGE_EXTS:
        return MediaUploadSafetyConstants.MAX_IMAGE_SIZE
    if ext in MediaUploadSafetyConstants.VIDEO_EXTS:
        return MediaUploadSafetyConstants.MAX_VIDEO_SIZE
    return MediaUploadSafetyConstants.MAX_AUDIO_SIZE


def save_upload_chunked(upload_file, file_path: str, ext: str) -> int:
    """分块读取上传文件写盘，带魔数校验与大小上限。

    Args:
        upload_file: starlette UploadFile（本函数读取其同步 .file 句柄，
            须在工作线程中调用）
        file_path: 目标落盘路径
        ext: 已通过白名单校验的扩展名（含点号）

    Returns:
        实际写入的字节数

    Raises:
        UploadValidationError: 魔数不匹配或超过大小上限（此时半成品文件已被清理）
    """
    max_size_bytes = max_upload_size_for_ext(ext)
    head = upload_file.file.read(MediaUploadSafetyConstants.MAGIC_SCAN_BYTES)

    check = _MAGIC_CHECKS.get(ext)
    if check is None or not check(head):
        raise UploadValidationError(
            f"文件内容与 {ext} 格式不符（魔数校验失败），请勿伪造文件扩展名"
        )

    total = 0
    try:
        with open(file_path, "wb") as f:
            f.write(head)
            total = len(head)
            while True:
                chunk = upload_file.file.read(MediaUploadSafetyConstants.CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_size_bytes:
                    limit_mb = max_size_bytes // (1024 * 1024)
                    raise UploadValidationError(f"文件大小超过限制（{limit_mb}MB）")
                f.write(chunk)
    except Exception:
        # 校验失败/写盘异常时清理半成品，避免无效文件残留并被对外服务
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            logger.warning(f"清理超限上传半成品失败: {file_path}")
        raise
    return total
