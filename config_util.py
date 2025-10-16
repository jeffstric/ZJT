"""
Configuration utility functions for ComfyUI server
"""
import os


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
