"""CLI 媒体偏好 Web API 同步逻辑与路由约定。"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from config.constant import (
    MediaGenerationMode,
    MediaGenerationSurface,
    MediaGenerationType,
)
from services.media_generation_preference_service import MediaGenerationPreferenceService


def test_cli_media_preferences_sync_reads_storyboard_cli_surface():
    from api.storyboard import _cli_media_preferences_sync

    calls = []

    def fake_get_profile(user_id, world_id, surface, media_type, mode, **kwargs):
        calls.append((user_id, world_id, surface, media_type, mode))
        return {
            "schema_version": 1,
            "task_id": 100 + len(calls),
            "model_key": f"{media_type}.{mode}",
            "model_name": f"{mode}",
        }

    with patch.object(
        MediaGenerationPreferenceService,
        "get_profile",
        side_effect=fake_get_profile,
    ):
        profiles = _cli_media_preferences_sync(7, 42)

    assert set(profiles.keys()) == {
        "image.text_to_image",
        "image.image_edit",
        "video.text_to_video",
        "video.image_to_video",
        "video.reference_to_video",
    }
    assert all(c[2] == MediaGenerationSurface.STORYBOARD_CLI for c in calls)
    assert all(c[0] == 7 and c[1] == 42 for c in calls)
    assert len(calls) == 5
    assert calls[0][3:] == (MediaGenerationType.IMAGE, MediaGenerationMode.TEXT_TO_IMAGE)


def test_cli_media_preference_routes_exist():
    from api.storyboard import router

    paths = {getattr(route, "path", None) for route in router.routes}
    assert "/api/storyboard/cli/media-preferences" in paths or any(
        "cli/media-preferences" in (p or "") for p in paths
    )
