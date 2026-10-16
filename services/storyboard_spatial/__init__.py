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


def build_three_scene(spatial_layout, spatial_world=None):
    return _impl().build_three_scene(spatial_layout, spatial_world)


def audit_spatial_layout(spatial_layout, spatial_world=None):
    return _impl().audit_spatial_layout(spatial_layout, spatial_world)


# three.js 代码契约（LLM 直出 three.js 空间方案）为纯字符串处理，
# 社区版/企业版行为一致，不进 edition 分发。
from .three_code import (  # noqa: E402
    audit_three_scene_code,
    audit_three_scene_codes_for_shots,
    build_three_code_preview,
    is_sequence_start_code,
    normalize_three_scene_code,
)


__all__ = [
    "StoryboardEnterpriseFeatureRequired",
    "build_spatial_prompt_context",
    "build_spatial_world_index",
    "derive_screen_projection",
    "repair_spatial_layout_continuity",
    "build_three_scene",
    "audit_spatial_layout",
    "audit_three_scene_code",
    "audit_three_scene_codes_for_shots",
    "build_three_code_preview",
    "is_sequence_start_code",
    "normalize_three_scene_code",
]
