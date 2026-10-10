"""Gemini 图片预览各聚合站点必须共用同步进程池，避免占住视觉调度线程。"""
from config.unified_config import UnifiedConfigRegistry


def test_gemini_image_preview_sites_are_all_sync_mode():
    for site in range(6):
        name = f"gemini_image_preview_site{site}_v1"
        impl = UnifiedConfigRegistry.get_implementation(name)
        assert impl is not None, name
        assert impl.sync_mode is True, name
