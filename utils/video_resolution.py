"""
视频分辨率校验工具。
"""
from typing import Optional
import logging

from config.unified_config import UnifiedConfigRegistry

logger = logging.getLogger(__name__)


def validate_video_resolution(resolution: Optional[str], impl_name: Optional[str]) -> Optional[str]:
    """
    校验视频分辨率参数，返回合法值或 None。

    - 实现方不支持分辨率选择时返回 None
    - 未传入时使用实现方默认值或首个支持值
    - 传入非法值时降级到默认值
    """
    if not impl_name:
        return resolution

    impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
    if not impl_config or not impl_config.supported_video_resolutions:
        return None

    valid_values = [
        item.get('value')
        for item in impl_config.supported_video_resolutions
        if isinstance(item, dict) and item.get('value')
    ]
    if not valid_values:
        return None

    default_resolution = impl_config.default_video_resolution or valid_values[0]
    if default_resolution not in valid_values:
        default_resolution = valid_values[0]

    if not resolution:
        return default_resolution

    if resolution not in valid_values:
        logger.warning(
            "Unsupported video resolution '%s' for implementation '%s'. Valid: %s. Falling back to '%s'.",
            resolution,
            impl_name,
            valid_values,
            default_resolution,
        )
        return default_resolution

    return resolution
