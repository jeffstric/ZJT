"""
文件存储工厂模块

提供统一的文件存储实例获取方法。

【线程池泄漏防护】
QiniuFileStorage 内部持有 ThreadPoolExecutor（4 workers），
若在业务代码中反复 `new QiniuFileStorage(...)`，会造成线程池实例累积、workers 永不释放。
统一通过 `get_file_storage(section=...)` 获取，按配置 section（如 "qiniu" / "qiniu_long_term"）
做参数化单例。
"""

import threading
from typing import Optional, Dict, Tuple

from .base import BaseFileStorage
from .qiniu_storage import QiniuFileStorage


# 按 (section, access_key, bucket_name, cdn_domain) 键的实例缓存。
# 允许配置热更新后自动切换到新实例；相同参数复用同一实例（同一线程池）。
_storage_instances: Dict[Tuple[str, str, str, str], BaseFileStorage] = {}
_storage_lock = threading.Lock()


def get_file_storage(
    config: dict = None,
    section: str = "qiniu",
) -> BaseFileStorage:
    """
    获取文件存储实例（按 section 参数化单例）

    Args:
        config: 配置字典，包含 file_storage 配置。
                如果为 None，则从全局配置读取。
        section: file_storage 下的子配置名，如 "qiniu"（默认，短期桶）
                 或 "qiniu_long_term"（长期桶）。

    Returns:
        BaseFileStorage: 文件存储实例

    Raises:
        ValueError: 配置缺失或不支持的存储类型

    Example:
        >>> storage = get_file_storage()
        >>> result = await storage.upload_file("images/test.jpg", "/path/to/file.jpg")
    """
    if config is None:
        config = _load_config()

    file_storage_config = config.get("file_storage", {}) or {}
    qiniu_config = file_storage_config.get(section)
    if not qiniu_config:
        raise ValueError(f"未找到有效的文件存储配置 section={section}，请检查 file_storage 配置项")

    access_key = qiniu_config.get("access_key") or ""
    secret_key = qiniu_config.get("secret_key") or ""
    bucket_name = qiniu_config.get("bucket_name") or ""
    cdn_domain = qiniu_config.get("cdn_domain") or ""

    if not (access_key and secret_key and bucket_name and cdn_domain):
        raise ValueError(f"file_storage.{section} 配置不完整（缺 access_key/secret_key/bucket_name/cdn_domain）")

    cache_key = (section, access_key, bucket_name, cdn_domain)
    with _storage_lock:
        inst = _storage_instances.get(cache_key)
        if inst is not None:
            return inst
        inst = QiniuFileStorage(
            access_key=access_key,
            secret_key=secret_key,
            bucket_name=bucket_name,
            cdn_domain=cdn_domain,
        )
        _storage_instances[cache_key] = inst
        return inst


def try_get_file_storage(
    config: dict = None,
    section: str = "qiniu",
) -> Optional[BaseFileStorage]:
    """
    与 get_file_storage 相同，但配置缺失时返回 None 而不是抛异常。
    适用于"配置可选"的调用点。
    """
    try:
        return get_file_storage(config=config, section=section)
    except ValueError:
        return None


def _load_config() -> dict:
    """
    从配置文件加载配置，并叠加 DB 动态配置覆盖 file_storage 部分。

    原来各调用点用 get_dynamic_config_value（DB 优先 + YAML 兜底）读取 qiniu 配置，
    统一走 factory 后若仅用 get_config()（纯 YAML），运维在 DB 后台修改的密钥/桶名
    将无法感知。这里在 YAML 配置基础上，用 get_dynamic_config_value 覆盖
    file_storage.{section} 的各字段，保持与旧代码一致的配置优先级。
    """
    from config.config_util import get_config, get_dynamic_config_value
    import copy

    config = get_config()
    file_storage = config.get("file_storage", {}) or {}
    # 深拷贝避免污染全局缓存
    merged = copy.deepcopy(file_storage)

    for section in ("qiniu", "qiniu_long_term"):
        for field in ("access_key", "secret_key", "bucket_name", "cdn_domain"):
            db_val = get_dynamic_config_value("file_storage", section, field, default=None)
            if db_val:
                if section not in merged:
                    merged[section] = {}
                merged[section][field] = db_val

    config["file_storage"] = merged
    return config


def reset_file_storage():
    """
    重置文件存储实例（主要用于测试）
    """
    with _storage_lock:
        _storage_instances.clear()
