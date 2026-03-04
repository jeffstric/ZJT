"""
文件存储工厂模块

提供统一的文件存储实例获取方法
"""

from typing import Optional

from .base import BaseFileStorage
from .qiniu_storage import QiniuFileStorage


# 全局存储实例缓存
_storage_instance: Optional[BaseFileStorage] = None


def get_file_storage(config: dict = None) -> BaseFileStorage:
    """
    获取文件存储实例（单例模式）

    Args:
        config: 配置字典，包含 file_storage 配置。
                如果为 None，则从全局配置读取。

    Returns:
        BaseFileStorage: 文件存储实例

    Raises:
        ValueError: 配置缺失或不支持的存储类型

    Example:
        >>> storage = get_file_storage()
        >>> result = await storage.upload_file("images/test.jpg", "/path/to/file.jpg")
    """
    global _storage_instance

    if _storage_instance is not None:
        return _storage_instance

    if config is None:
        # 从全局配置文件读取
        config = _load_config()

    file_storage_config = config.get("file_storage", {})

    # 目前只支持七牛云
    qiniu_config = file_storage_config.get("qiniu")
    if qiniu_config:
        _storage_instance = QiniuFileStorage(
            access_key=qiniu_config.get("access_key"),
            secret_key=qiniu_config.get("secret_key"),
            bucket_name=qiniu_config.get("bucket_name"),
            cdn_domain=qiniu_config.get("cdn_domain")
        )
        return _storage_instance

    raise ValueError("未找到有效的文件存储配置，请检查 file_storage 配置项")


def _load_config() -> dict:
    """从配置文件加载配置"""
    from config.config_util import get_config
    return get_config()


def reset_file_storage():
    """
    重置文件存储实例（主要用于测试）
    """
    global _storage_instance
    _storage_instance = None
