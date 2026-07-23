from types import SimpleNamespace

import pytest

from config.constant import (
    MediaGenerationErrorCode,
    MediaGenerationMode,
    MediaGenerationSurface,
    MediaGenerationType,
)
from config.unified_config import ImageMode, TaskCategory
from services.media_generation_preference_service import (
    MediaGenerationPreferenceError,
    MediaGenerationPreferenceService,
)


def _config(
    task_id=11,
    *,
    category=TaskCategory.TEXT_TO_IMAGE,
    categories=None,
    hidden=False,
    enabled=True,
    supported_image_modes=None,
    supports_ref_audio_video=False,
):
    return SimpleNamespace(
        id=task_id,
        key=f"model-{task_id}",
        name=f"Model {task_id}",
        category=category,
        categories=categories or [],
        enabled=enabled,
        hidden=hidden,
        supported_image_modes=supported_image_modes or [],
        supports_ref_audio_video=supports_ref_audio_video,
        sort_order=task_id,
    )


def test_fifteen_preference_namespaces_are_unique():
    names = {
        MediaGenerationPreferenceService.preference_type(surface, media_type, mode)
        for surface in MediaGenerationSurface.ALL
        for media_type, modes in (
            (MediaGenerationType.IMAGE, MediaGenerationMode.IMAGE_MODES),
            (MediaGenerationType.VIDEO, MediaGenerationMode.VIDEO_MODES),
        )
        for mode in modes
    }
    assert len(names) == 15


@pytest.mark.parametrize(
    ("media_type", "kwargs", "expected"),
    [
        (MediaGenerationType.IMAGE, {}, MediaGenerationMode.TEXT_TO_IMAGE),
        (MediaGenerationType.IMAGE, {"image_urls": ["a"]}, MediaGenerationMode.IMAGE_EDIT),
        (MediaGenerationType.VIDEO, {}, MediaGenerationMode.TEXT_TO_VIDEO),
        (MediaGenerationType.VIDEO, {"image_urls": ["a"]}, MediaGenerationMode.IMAGE_TO_VIDEO),
        (
            MediaGenerationType.VIDEO,
            {"image_urls": ["a"], "image_mode": "first_last_with_ref"},
            MediaGenerationMode.REFERENCE_TO_VIDEO,
        ),
        (
            MediaGenerationType.VIDEO,
            {"audio_urls": ["a"]},
            MediaGenerationMode.REFERENCE_TO_VIDEO,
        ),
    ],
)
def test_determine_mode_uses_real_inputs(media_type, kwargs, expected):
    assert MediaGenerationPreferenceService.determine_mode(media_type, **kwargs) == expected


def test_hidden_model_is_rejected_for_new_request(monkeypatch):
    monkeypatch.setattr(
        "services.media_generation_preference_service.UnifiedConfigRegistry.get_by_id",
        lambda task_id: _config(task_id, hidden=True),
    )
    with pytest.raises(MediaGenerationPreferenceError) as exc_info:
        MediaGenerationPreferenceService.validate_model(
            11,
            MediaGenerationType.IMAGE,
            MediaGenerationMode.TEXT_TO_IMAGE,
        )
    assert exc_info.value.code == MediaGenerationErrorCode.MODEL_HIDDEN


def test_persisted_snapshot_can_validate_hidden_model(monkeypatch):
    monkeypatch.setattr(
        "services.media_generation_preference_service.UnifiedConfigRegistry.get_by_id",
        lambda task_id: _config(task_id, hidden=True),
    )
    config = MediaGenerationPreferenceService.validate_model(
        11,
        MediaGenerationType.IMAGE,
        MediaGenerationMode.TEXT_TO_IMAGE,
        allow_hidden=True,
    )
    assert config.id == 11


def test_first_last_with_ref_requires_reference_video_capability(monkeypatch):
    config = _config(
        category=TaskCategory.IMAGE_TO_VIDEO,
        supported_image_modes=[ImageMode.FIRST_LAST_FRAME, ImageMode.MULTI_REFERENCE],
    )
    monkeypatch.setattr(
        "services.media_generation_preference_service.UnifiedConfigRegistry.get_by_id",
        lambda task_id: config,
    )
    resolved = MediaGenerationPreferenceService.validate_model(
        config.id,
        MediaGenerationType.VIDEO,
        MediaGenerationMode.REFERENCE_TO_VIDEO,
        image_mode="first_last_with_ref",
    )
    assert resolved is config


def test_save_profile_writes_only_its_surface_slot(monkeypatch):
    config = _config()
    writes = []
    monkeypatch.setattr(
        "services.media_generation_preference_service.UnifiedConfigRegistry.get_by_id",
        lambda task_id: config,
    )
    monkeypatch.setattr(
        "services.media_generation_preference_service.UserPreferencesModel.upsert",
        lambda *args: writes.append(args),
    )
    saved = MediaGenerationPreferenceService.save_profile(
        1,
        2,
        MediaGenerationSurface.STORYBOARD_CLI,
        MediaGenerationType.IMAGE,
        MediaGenerationMode.TEXT_TO_IMAGE,
        {"task_id": config.id, "ratio": "16:9", "ignored": "value"},
    )
    assert saved["task_id"] == config.id
    assert "ignored" not in saved
    assert writes[0][2] == "media_pref.storyboard_cli.image.text_to_image"
