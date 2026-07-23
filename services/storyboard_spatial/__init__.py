"""Storyboard spatial facade.

Community edition exposes legacy-compatible helpers only. Enterprise edition
loads the full spatial engine from `enterprise.services.storyboard_spatial`.
"""

from config.constant import Edition

from .exceptions import StoryboardEnterpriseFeatureRequired


def _impl():
    if Edition.is_enterprise():
        from enterprise.services import storyboard_spatial as enterprise_spatial

        return enterprise_spatial

    from . import community

    return community


def build_spatial_prompt_context(spatial_layout, spatial_world=None):
    return _impl().build_spatial_prompt_context(spatial_layout, spatial_world)


def build_spatial_world_index(parsed_or_prompt):
    return _impl().build_spatial_world_index(parsed_or_prompt)


def derive_screen_projection(entity, camera_pose, world_index):
    return _impl().derive_screen_projection(entity, camera_pose, world_index)


def repair_spatial_layout_continuity(parsed_data):
    return _impl().repair_spatial_layout_continuity(parsed_data)


__all__ = [
    "StoryboardEnterpriseFeatureRequired",
    "build_spatial_prompt_context",
    "build_spatial_world_index",
    "derive_screen_projection",
    "repair_spatial_layout_continuity",
]
