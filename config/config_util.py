"""
Configuration utility functions for ComfyUI server
"""
import os
import yaml
from typing import Any, Dict, Optional

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
