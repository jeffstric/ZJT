"""
剪映工具函数模块
"""

from typing import Union


def seconds_to_microseconds(seconds: Union[int, float]) -> int:
    """
    将秒转换为微秒
    
    Args:
        seconds: 秒数
        
    Returns:
        微秒数
    """
    return int(seconds * 1000000)


def microseconds_to_seconds(microseconds: int) -> float:
    """
    将微秒转换为秒
    
    Args:
        microseconds: 微秒数
        
    Returns:
        秒数
    """
    return microseconds / 1000000.0


def time_to_microseconds(time_str: str) -> int:
    """
    将时间字符串转换为微秒
    支持格式: "MM:SS", "HH:MM:SS", "SS"
    
    Args:
        time_str: 时间字符串
        
    Returns:
        微秒数
    """
    parts = time_str.split(':')
    
    if len(parts) == 1:  # SS
        seconds = float(parts[0])
    elif len(parts) == 2:  # MM:SS
        minutes = int(parts[0])
        seconds = float(parts[1])
        seconds += minutes * 60
    elif len(parts) == 3:  # HH:MM:SS
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        seconds += hours * 3600 + minutes * 60
    else:
        raise ValueError(f"不支持的时间格式: {time_str}")
    
    return seconds_to_microseconds(seconds)


def format_duration(microseconds: int) -> str:
    """
    格式化时长显示
    
    Args:
        microseconds: 微秒数
        
    Returns:
        格式化的时长字符串
    """
    seconds = microseconds / 1000000.0
    
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        remaining_seconds = seconds % 60
        return f"{minutes}分{remaining_seconds:.1f}秒"
    else:
        hours = int(seconds // 3600)
        remaining_minutes = int((seconds % 3600) // 60)
        remaining_seconds = seconds % 60
        return f"{hours}时{remaining_minutes}分{remaining_seconds:.1f}秒"
