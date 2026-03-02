"""
Configuration utility functions for ComfyUI server
"""
import os
import time
import logging
import yaml
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 全局配置缓存
_config_cache: Dict[str, Any] = {}


def get_config(config_path: str = None) -> Dict[str, Any]:
    """
    获取配置文件内容（带缓存）
    
    首次调用时读取配置文件并缓存，后续调用直接返回缓存内容。
    
    Args:
        config_path: 可选的配置文件路径，默认根据环境变量自动选择
        
    Returns:
        配置文件内容的字典
        
    Example:
        >>> config = get_config()
        >>> db_config = config.get('database', {})
        >>> edition_mode = config.get('edition', {}).get('mode', 'community')
    """
    global _config_cache
    
    # 获取配置文件路径
    file_path = get_config_path(config_path)
    
    # 检查缓存
    if file_path in _config_cache:
        return _config_cache[file_path]

    # __file__ 在 config/config_util.py，配置文件在项目根目录
    config_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(config_dir)  # 回到项目根目录
    full_path = os.path.join(project_root, file_path)
    
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Configuration file not found: {full_path}")
    
    # 读取并缓存
    with open(full_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
        _config_cache[file_path] = config or {}
    
    return _config_cache[file_path]


def get_config_value(*keys, default: Any = None) -> Any:
    """
    获取配置文件中的指定值（支持多层级键）
    
    ⚠️ 推荐使用 get_dynamic_config_value() 替代本函数！
    get_dynamic_config_value() 会优先从数据库读取配置，支持后台动态修改，
    如果数据库中不存在则自动降级到 YAML 配置文件。
    
    本函数仅从 YAML 配置文件读取，不支持动态修改。
    仅在以下场景使用本函数：
    - 数据库连接配置（数据库初始化前无法查询数据库）
    - 不需要动态修改的固定配置
    
    Args:
        *keys: 配置键路径，如 'database', 'host' 表示 config['database']['host']
        default: 键不存在时的默认值
        
    Returns:
        配置值或默认值
        
    Example:
        >>> get_config_value('database', 'host', default='localhost')
        >>> get_config_value('edition', 'mode', default='community')
    """
    config = get_config()
    
    result = config
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key)
        else:
            return default
        if result is None:
            return default
    
    return result if result is not None else default


def resolve_bin_path(config_path: str, app_dir: str) -> str:
    """
    解析可执行文件路径

    - 如果是绝对路径，直接使用
    - 如果是相对路径，基于 app_dir 解析为绝对路径
    - 如果是纯命令名（无路径分隔符），直接使用（依赖 PATH）

    Args:
        config_path: 配置文件中的路径值
        app_dir: 应用根目录路径

    Returns:
        解析后的完整路径或命令名
    """
    if not config_path:
        return None

    # 如果是纯命令名（无路径分隔符），直接使用
    if os.sep not in config_path and '/' not in config_path:
        return config_path

    # 如果已经是绝对路径，直接使用
    if os.path.isabs(config_path):
        return config_path

    # 相对路径：基于 app_dir 解析
    return os.path.join(app_dir, config_path)


def get_config_path(config_path: str = None) -> str:
    """
    Get configuration file path based on environment variable
    
    Args:
        config_path: Optional explicit config path. If provided, returns as-is.
        
    Returns:
        Path to configuration file
        - If comfyui_env is not set: config_dev.yml (default development)
        - If comfyui_env is set: config_{env}.yml (e.g., config_prod.yml)
        
    Example:
        >>> # When comfyui_env is not set
        >>> get_config_path()
        'config_dev.yml'
        >>> # When comfyui_env=prod
        >>> get_config_path()
        'config_prod.yml'
        >>> # Explicit path
        >>> get_config_path("custom.yml")
        'custom.yml'
    """
    if config_path is not None:
        return config_path
    
    env = os.getenv("comfyui_env")
    
    # If env variable is not set, default to dev
    if env is None:
        return "config_dev.yml"
    
    # If env variable is set, use config_{env}.yml format
    return f"config_{env}.yml"


def is_dev_environment() -> bool:
    """
    Check if running in development environment
    
    Returns:
        True if comfyui_env is not set or equals 'dev', False otherwise
    """
    env = os.getenv("comfyui_env")
    return env is None or env == "dev"


# ==================== 动态配置（数据库优先 + YAML 兜底）====================

# 动态配置缓存: {"{env}:{config_key}": {"value": Any, "expire_at": float}}
_dynamic_config_cache: Dict[str, Dict[str, Any]] = {}
# 缓存 TTL（秒）
_DYNAMIC_CACHE_TTL = 30


def get_current_env() -> str:
    """
    获取当前环境标识
    
    Returns:
        环境标识字符串，如 'dev', 'prod', 'test'
    """
    env = os.getenv("comfyui_env")
    return env if env else "dev"


def get_dynamic_config_value(*keys, default: Any = None) -> Any:
    """
    获取动态配置值（数据库优先 + YAML 兜底）
    
    优先从数据库读取配置，如果数据库中不存在则回退到 YAML 配置文件。
    使用内存缓存 + TTL 实现热更新。
    
    Args:
        *keys: 配置键路径，如 'task_queue', 'max_retry_count'
        default: 键不存在时的默认值
        
    Returns:
        配置值或默认值
        
    Example:
        >>> get_dynamic_config_value('task_queue', 'max_retry_count', default=30)
        >>> get_dynamic_config_value('runninghub', 'api_key', default='')
    """
    global _dynamic_config_cache
    
    # 构建 config_key
    config_key = '.'.join(keys)
    env = get_current_env()
    cache_key = f"{env}:{config_key}"
    
    # 检查缓存是否有效
    now = time.time()
    if cache_key in _dynamic_config_cache:
        cached = _dynamic_config_cache[cache_key]
        if cached['expire_at'] > now:
            return cached['value']
    
    # 尝试从数据库读取
    try:
        from model.system_config import SystemConfigModel
        config = SystemConfigModel.get_by_key(env, config_key)
        if config:
            value = config.get_typed_value()
            # 更新缓存
            _dynamic_config_cache[cache_key] = {
                'value': value,
                'expire_at': now + _DYNAMIC_CACHE_TTL
            }
            return value
    except Exception as e:
        logger.warning(f"Failed to get dynamic config from database: {e}, falling back to YAML")
    
    # 回退到 YAML 配置
    yaml_value = get_config_value(*keys, default=default)
    
    # 缓存 YAML 值（避免频繁数据库查询）
    _dynamic_config_cache[cache_key] = {
        'value': yaml_value,
        'expire_at': now + _DYNAMIC_CACHE_TTL
    }
    
    return yaml_value


def set_dynamic_config_value(
    *keys,
    value: Any,
    value_type: str = 'string',
    description: str = None,
    editable: int = 1,
    is_sensitive: int = 0,
    updated_by: int = None
) -> int:
    """
    设置动态配置值（写入数据库）
    
    Args:
        *keys: 配置键路径
        value: 配置值
        value_type: 值类型 ('string', 'int', 'float', 'bool', 'json')
        description: 配置描述
        editable: 是否可编辑
        is_sensitive: 是否敏感配置
        updated_by: 修改人 user_id
        
    Returns:
        配置 ID
    """
    import json as json_module
    
    config_key = '.'.join(keys)
    env = get_current_env()
    
    # 将值转换为字符串存储
    if value_type == 'json':
        config_value = json_module.dumps(value, ensure_ascii=False)
    elif value_type == 'bool':
        config_value = 'true' if value else 'false'
    else:
        config_value = str(value)
    
    from model.system_config import SystemConfigModel
    from model.system_config_history import SystemConfigHistoryModel
    
    # 获取旧值（用于记录历史）
    old_config = SystemConfigModel.get_by_key(env, config_key)
    old_value = old_config.config_value if old_config else None
    
    # 插入或更新配置
    config_id = SystemConfigModel.upsert(
        env=env,
        config_key=config_key,
        config_value=config_value,
        value_type=value_type,
        description=description,
        editable=editable,
        is_sensitive=is_sensitive,
        updated_by=updated_by
    )
    
    # 记录修改历史
    if old_value != config_value:
        SystemConfigHistoryModel.create(
            config_id=config_id,
            env=env,
            config_key=config_key,
            old_value=old_value,
            new_value=config_value,
            value_type=value_type,
            is_sensitive=is_sensitive,
            updated_by=updated_by
        )
    
    # 清除缓存
    invalidate_dynamic_cache(config_key)
    
    return config_id


def invalidate_dynamic_cache(config_key: str = None) -> None:
    """
    清除动态配置缓存
    
    Args:
        config_key: 配置键，为空则清除所有缓存
    """
    global _dynamic_config_cache
    
    if config_key is None:
        _dynamic_config_cache.clear()
        logger.info("Cleared all dynamic config cache")
    else:
        env = get_current_env()
        cache_key = f"{env}:{config_key}"
        if cache_key in _dynamic_config_cache:
            del _dynamic_config_cache[cache_key]
            logger.info(f"Cleared dynamic config cache for {cache_key}")


def reload_all_dynamic_configs() -> None:
    """
    重新加载所有动态配置（清除缓存）
    """
    invalidate_dynamic_cache()
    logger.info("Reloaded all dynamic configs")
