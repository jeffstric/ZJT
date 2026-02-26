"""
File Storage Module - 文件存储抽象层

提供统一的文件存储接口，支持多种存储后端（如七牛云、阿里云OSS等）
"""

from .base import BaseFileStorage
from .qiniu_storage import QiniuFileStorage
from .factory import get_file_storage

__all__ = [
    "BaseFileStorage",
    "QiniuFileStorage",
    "get_file_storage",
]
