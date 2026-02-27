"""
日志截断工具 - 用于生产环境中截断过长的日志内容
"""

import os
import json
from typing import Any, Union

# 生产环境检测
IS_PRODUCTION = os.environ.get('ENVIRONMENT', 'development').lower() == 'production'

# 日志截断配置
MAX_LOG_LENGTH = 1000 if IS_PRODUCTION else 10000  # 生产环境更短的日志
MAX_JSON_LOG_LENGTH = 500 if IS_PRODUCTION else 2000  # JSON日志更短
TRUNCATE_SUFFIX = "...[truncated]"

def truncate_log_content(content: Any, max_length: int = None) -> str:
    """
    截断日志内容以适应生产环境
    
    Args:
        content: 要记录的内容（任意类型）
        max_length: 最大长度，如果为None则使用默认配置
        
    Returns:
        截断后的字符串
    """
    if max_length is None:
        max_length = MAX_LOG_LENGTH
    
    # 转换为字符串
    if isinstance(content, (dict, list)):
        # 对于复杂对象，先序列化为JSON再截断
        try:
            json_str = json.dumps(content, ensure_ascii=False, indent=2)
            if len(json_str) > max_length:
                return json_str[:max_length] + TRUNCATE_SUFFIX
            return json_str
        except:
            # JSON序列化失败，使用str()
            content_str = str(content)
    else:
        content_str = str(content)
    
    # 截断长内容
    if len(content_str) > max_length:
        return content_str[:max_length] + TRUNCATE_SUFFIX
    
    return content_str

def truncate_json_log(data: Any, max_length: int = None) -> str:
    """
    专门用于JSON日志的截断，保持JSON格式
    
    Args:
        data: 要记录的数据
        max_length: 最大长度，如果为None则使用默认配置
        
    Returns:
        截断后的JSON字符串
    """
    if max_length is None:
        max_length = MAX_JSON_LOG_LENGTH
    
    try:
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        if len(json_str) > max_length:
            # 尝试智能截断：保留结构但截断长字符串字段
            truncated_data = _truncate_json_fields(data, max_length)
            return json.dumps(truncated_data, ensure_ascii=False, indent=2)
        return json_str
    except:
        # JSON序列化失败
        return truncate_log_content(str(data), max_length)

def _truncate_json_fields(data: Any, max_length: int) -> Any:
    """
    递归截断JSON对象中的长字符串字段
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            result[key] = _truncate_json_fields(value, max_length)
        return result
    elif isinstance(data, list):
        return [_truncate_json_fields(item, max_length) for item in data]
    elif isinstance(data, str):
        if len(data) > max_length // 4:  # 为每个字段分配1/4的空间
            return data[:max_length // 4] + TRUNCATE_SUFFIX
        return data
    else:
        return data

def should_log_debug() -> bool:
    """
    判断是否应该记录DEBUG级别日志
    生产环境下只记录WARNING及以上级别
    """
    return not IS_PRODUCTION

def should_log_info() -> bool:
    """
    判断是否应该记录INFO级别日志
    生产环境下可以选择性关闭INFO日志
    """
    # 可以通过环境变量控制
    return os.environ.get('LOG_INFO_IN_PRODUCTION', 'true').lower() == 'true' or not IS_PRODUCTION

def safe_log_message(message: str, data: Any = None, max_length: int = None) -> tuple[str, str]:
    """
    安全地生成日志消息，自动截断
    
    Returns:
        tuple: (message, data_str) 都已经过截断处理
    """
    safe_message = truncate_log_content(message, max_length)
    safe_data = truncate_json_log(data, max_length) if data is not None else None
    return safe_message, safe_data
