"""
剪映多轨道草稿生成库
"""

from .core import JianyingMultiTrackLibrary
from .utils import seconds_to_microseconds, time_to_microseconds, microseconds_to_seconds
from .config import Config
from .media_utils import MediaUtils

__version__ = "1.0.0"
__all__ = [
    "JianyingMultiTrackLibrary",
    "seconds_to_microseconds", 
    "time_to_microseconds",
    "microseconds_to_seconds",
    "Config",
    "MediaUtils"
]
