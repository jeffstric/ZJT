"""script_writer 对话切生图模型：任务快照应使用请求/会话草稿而非脏 media_pref。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from config.constant import MediaGenerationMode, MediaGenerationType
from config.unified_config import TaskCategory


def _config(task_id, *, category=TaskCategory.IMAGE_EDIT, categories=None, name=None):
    return SimpleNamespace(
        id=task_id,
        key=f"model-{task_id}",
        name=name or f"Model {task_id}",
        category=category,
        categories=categories or [TaskCategory.TEXT_TO_IMAGE],
        enabled=True,
        hidden=False,
        supported_image_modes=[],
        supports_ref_audio_video=False,
        sort_order=task_id,
    )


def test_apply_image_task_id_overrides_both_image_slots(monkeypatch):
    from api import script_writer as sw

    dual = _config(33, name="Seedream 5.0 Pro")
    monkeypatch.setattr(
        "services.media_generation_preference_service.UnifiedConfigRegistry.get_by_id",
        lambda task_id: dual if int(task_id) == 33 else _config(task_id),
    )
    saved = []

    def _save(user_id, world_id, surface, media_type, mode, profile):
        saved.append(mode)
        return {
            "schema_version": 1,
            "task_id": int(profile["task_id"]),
            "model_key": dual.key,
            "model_name": dual.name,
        }

    monkeypatch.setattr(sw.MediaGenerationPreferenceService, "save_profile", _save)

    profiles = {
        "image.text_to_image": {
            "task_id": 26,
            "model_key": "gpt",
            "model_name": "GPT",
            "schema_version": 1,
        },
        "image.image_edit": {
            "task_id": 26,
            "model_key": "gpt",
            "model_name": "GPT",
            "schema_version": 1,
        },
    }
    request_slots = set()
    sw._apply_image_task_id_to_execution_profiles(
        "1",
        "101",
        profiles,
        request_slots,
        {"task_id": 33},
        33,
        persist_world_default=True,
    )
    assert MediaGenerationMode.TEXT_TO_IMAGE in saved
    assert MediaGenerationMode.IMAGE_EDIT in saved
    assert profiles["image.text_to_image"]["task_id"] == 33
    assert profiles["image.image_edit"]["task_id"] == 33
    assert "image.text_to_image" in request_slots
    assert "image.image_edit" in request_slots


def test_build_context_uses_request_image_task_id(monkeypatch):
    from api import script_writer as sw

    dual = _config(33, name="Seedream 5.0 Pro")
    dirty = {
        "task_id": 26,
        "model_key": "model-26",
        "model_name": "GPT Image 2 图片编辑",
        "schema_version": 1,
    }
    monkeypatch.setattr(
        "services.media_generation_preference_service.UnifiedConfigRegistry.get_by_id",
        lambda task_id: dual if int(task_id) == 33 else _config(int(task_id)),
    )
    # 只提供 image 槽位，避免 video 校验干扰本用例
    monkeypatch.setattr(
        sw,
        "_marketing_media_preferences_sync",
        lambda user_id, world_id: {
            "image.text_to_image": dict(dirty),
            "image.image_edit": dict(dirty),
        },
    )
    monkeypatch.setattr(
        sw.MediaGenerationPreferenceService,
        "save_profile",
        lambda user_id, world_id, surface, media_type, mode, profile: {
            "schema_version": 1,
            "task_id": int(profile["task_id"]),
            "model_key": dual.key,
            "model_name": dual.name,
        },
    )

    req = MagicMock()
    req.image_preferences = {"task_id": 33, "model_name": "Seedream 5.0 Pro"}
    req.video_preferences = None
    req.image_urls = None
    req.video_urls = None
    req.audio_urls = None

    ctx = sw._build_marketing_task_execution_context_sync("1", "101", req)
    snaps = ctx["generation_snapshots"]
    assert snaps["image.text_to_image"]["task_id"] == 33
    assert snaps["image.image_edit"]["task_id"] == 33
    assert snaps["image.text_to_image"]["model_source"] == "request"


def test_resolve_image_task_accepts_canonical_and_legacy_model_names(monkeypatch):
    """统一模型名上线后，新请求和旧快照都必须能反查同一 task_id。"""
    from api import script_writer as sw
    from config.unified_config import ALL_TASK_CONFIGS, TaskTypeId

    gpt_image = next(
        config for config in ALL_TASK_CONFIGS
        if config.id == TaskTypeId.GPT_IMAGE_2_EDIT
    )
    monkeypatch.setattr(sw.UnifiedConfigRegistry, "get_all", lambda: [gpt_image])

    assert sw._resolve_explicit_image_task_id(
        {"model_name": "GPT Image 2"}, MediaGenerationMode.IMAGE_EDIT
    ) == TaskTypeId.GPT_IMAGE_2_EDIT
    assert sw._resolve_explicit_image_task_id(
        {"model_name": "GPT Image 2 图片编辑"}, MediaGenerationMode.IMAGE_EDIT
    ) == TaskTypeId.GPT_IMAGE_2_EDIT


def test_apply_video_task_id_overrides_all_compatible_video_slots(monkeypatch):
    from api import script_writer as sw
    from config.unified_config import UnifiedConfigRegistry, init_unified_config

    UnifiedConfigRegistry._configs.clear()
    UnifiedConfigRegistry._id_map.clear()
    UnifiedConfigRegistry._implementations.clear()
    init_unified_config()

    saved = []

    def _save(user_id, world_id, surface, media_type, mode, profile):
        saved.append((mode, int(profile["task_id"])))
        cfg = UnifiedConfigRegistry.get_by_id(int(profile["task_id"]))
        return {
            "schema_version": 1,
            "task_id": int(cfg.id),
            "model_key": cfg.key,
            "model_name": cfg.name,
        }

    monkeypatch.setattr(sw.MediaGenerationPreferenceService, "save_profile", _save)

    seedance = UnifiedConfigRegistry.get_by_key("seedance_2_5_image_to_video")
    h3_r2v = UnifiedConfigRegistry.get_by_key("minimax_h3_reference_to_video")
    profiles = {
        "video.text_to_video": {"task_id": h3_r2v.id, "model_key": h3_r2v.key},
        "video.image_to_video": {"task_id": h3_r2v.id, "model_key": h3_r2v.key},
        "video.reference_to_video": {"task_id": h3_r2v.id, "model_key": h3_r2v.key},
    }
    request_slots = set()
    sw._apply_video_task_id_to_execution_profiles(
        "1",
        "101",
        profiles,
        request_slots,
        {"task_id": seedance.id},
        seedance.id,
        persist_world_default=True,
    )
    saved_modes = {mode for mode, _ in saved}
    assert MediaGenerationMode.TEXT_TO_VIDEO in saved_modes
    assert MediaGenerationMode.IMAGE_TO_VIDEO in saved_modes
    assert MediaGenerationMode.REFERENCE_TO_VIDEO in saved_modes
    assert profiles["video.reference_to_video"]["task_id"] == seedance.id
    assert profiles["video.image_to_video"]["task_id"] == seedance.id
    UnifiedConfigRegistry._configs.clear()
    UnifiedConfigRegistry._id_map.clear()
    UnifiedConfigRegistry._implementations.clear()

