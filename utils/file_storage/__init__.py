"""
File Storage Module - 文件存储抽象层

提供统一的文件存储接口，支持多种存储后端（如七牛云、阿里云OSS等）
"""

from .base import BaseFileStorage, UploadResult
from .qiniu_storage import QiniuFileStorage
from .runninghub_storage import RunningHubFileStorage
from .factory import get_file_storage

__all__ = [
    "BaseFileStorage",
    "UploadResult",
    "QiniuFileStorage",
    "RunningHubFileStorage",
    "get_file_storage",
]
