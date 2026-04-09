"""
MIME Type detection utilities

Uses magic bytes for accurate detection when filetype library is available,
falls back to extension-based detection otherwise.
"""
import os

try:
    import filetype

    HAS_FILETYPE = True
except ImportError:
    HAS_FILETYPE = False

# Extension to MIME type mapping (fallback when filetype not available)
EXT_MIME_MAP = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
    '.tiff': 'image/tiff',
    '.tif': 'image/tiff',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.mov': 'video/quicktime',
    '.avi': 'video/x-msvideo',
    '.mkv': 'video/x-matroska',
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.ogg': 'audio/ogg',
    '.pdf': 'application/pdf',
    '.zip': 'application/zip',
    '.json': 'application/json',
    '.xml': 'application/xml',
    '.html': 'text/html',
    '.htm': 'text/html',
    '.txt': 'text/plain',
}


def get_mime_type(file_path: str) -> str:
    """
    Detect MIME type of a file.

    Uses magic bytes (first ~20 bytes) for accurate detection when filetype
    library is available, falls back to extension-based detection otherwise.

    Args:
        file_path: Path to the file

    Returns:
        MIME type string (e.g., 'image/jpeg', 'video/mp4')
        Returns 'application/octet-stream' if unknown
    """
    if HAS_FILETYPE and os.path.exists(file_path):
        kind = filetype.guess(file_path)
        if kind:
            return kind.mime

    ext = os.path.splitext(file_path)[1].lower()
    return EXT_MIME_MAP.get(ext, 'application/octet-stream')


def get_mime_type_from_extension(ext: str) -> str:
    """
    Get MIME type from file extension only (no file system access).

    Args:
        ext: File extension (with or without leading dot, e.g., '.jpg' or 'jpg')

    Returns:
        MIME type string
    """
    if not ext.startswith('.'):
        ext = '.' + ext
    return EXT_MIME_MAP.get(ext.lower(), 'application/octet-stream')
