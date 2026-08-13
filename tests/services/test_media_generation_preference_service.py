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


def test_hidden_model_is_rejected_for_preference_selection(monkeypatch):
    """偏好保存/默认模型路径：hidden 模型不可选。"""
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


def test_allow_hidden_accepts_internal_or_snapshot_models(monkeypatch):
    """直接 API 显式 task_id / 已持久化 snapshot：allow_hidden=True 可放行。"""
    monkeypatch.setattr(
        "services.media_generation_preference_service.UnifiedConfigRegistry.get_by_id",
        lambda task_id: _config(
            task_id,
            category=TaskCategory.IMAGE_EDIT,
            hidden=True,
        ),
    )
    config = MediaGenerationPreferenceService.validate_model(
        11,
        MediaGenerationType.IMAGE,
        MediaGenerationMode.IMAGE_EDIT,
        allow_hidden=True,
    )
    assert config.id == 11


def test_qwen_multi_angle_image_edit_allowed_with_allow_hidden():
    """多角度内部模型：偏好不可选，直接 image-edit 校验可放行。"""
    from config.unified_config import TaskTypeId, UnifiedConfigRegistry

    config = UnifiedConfigRegistry.get_by_id(TaskTypeId.QWEN_MULTI_ANGLE_IMAGE)
    assert config is not None
    assert config.hidden is True
    assert config.enabled is True

    with pytest.raises(MediaGenerationPreferenceError) as exc_info:
        MediaGenerationPreferenceService.validate_model(
            config.id,
            MediaGenerationType.IMAGE,
            MediaGenerationMode.IMAGE_EDIT,
        )
    assert exc_info.value.code == MediaGenerationErrorCode.MODEL_HIDDEN

    resolved = MediaGenerationPreferenceService.validate_model(
        config.id,
        MediaGenerationType.IMAGE,
        MediaGenerationMode.IMAGE_EDIT,
        allow_hidden=True,
    )
    assert resolved.id == config.id
    assert resolved.key == "qwen-multi-angle"


def test_reference_only_model_rejected_for_image_to_video_slot(monkeypatch):
    """Vidu-Q2 等仅 multi_reference 的模型不能写入图生视频槽位。"""
    config = _config(
        category=TaskCategory.IMAGE_TO_VIDEO,
        supported_image_modes=[ImageMode.MULTI_REFERENCE],
    )
    monkeypatch.setattr(
        "services.media_generation_preference_service.UnifiedConfigRegistry.get_by_id",
        lambda task_id: config,
    )
    with pytest.raises(MediaGenerationPreferenceError) as exc_info:
        MediaGenerationPreferenceService.validate_model(
            config.id,
            MediaGenerationType.VIDEO,
            MediaGenerationMode.IMAGE_TO_VIDEO,
        )
    assert exc_info.value.code == MediaGenerationErrorCode.MODEL_INPUT_UNSUPPORTED


def test_vidu_q2_cannot_be_saved_as_image_to_video_preference(monkeypatch):
    """仅 multi_reference 的模型（如 Vidu-Q2）：图生视频槽位拒绝，参考生视频放行。"""
    config = _config(
        category=TaskCategory.IMAGE_TO_VIDEO,
        supported_image_modes=[ImageMode.MULTI_REFERENCE],
    )
    monkeypatch.setattr(
        "services.media_generation_preference_service.UnifiedConfigRegistry.get_by_id",
        lambda task_id: config,
    )
    assert ImageMode.FIRST_LAST_FRAME not in (config.supported_image_modes or [])
    with pytest.raises(MediaGenerationPreferenceError) as exc_info:
        MediaGenerationPreferenceService.validate_model(
            config.id,
            MediaGenerationType.VIDEO,
            MediaGenerationMode.IMAGE_TO_VIDEO,
        )
    assert exc_info.value.code == MediaGenerationErrorCode.MODEL_INPUT_UNSUPPORTED
    resolved = MediaGenerationPreferenceService.validate_model(
        config.id,
        MediaGenerationType.VIDEO,
        MediaGenerationMode.REFERENCE_TO_VIDEO,
        image_mode=ImageMode.MULTI_REFERENCE,
    )
    assert resolved.id == config.id


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
