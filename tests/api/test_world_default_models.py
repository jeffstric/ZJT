"""世界默认对话/生图模型 API 与 scope 行为。"""

from unittest.mock import MagicMock


def test_set_default_llm_model_normalizes_payload(monkeypatch):
    from api import script_writer as sw
    from model.user_preferences import PREF_TYPE_DEFAULT_LLM_MODEL

    writes = []
    monkeypatch.setattr(
        sw.UserPreferencesModel,
        "upsert",
        lambda user_id, world_id, pref_type, value: writes.append(
            (user_id, world_id, pref_type, value)
        ),
    )
    saved = sw.set_default_llm_model(
        "1",
        "101",
        {"model": "gemini-3-flash-preview", "model_id": "1010", "vendor_id": 1, "name": "Gemini"},
    )
    assert saved["model"] == "gemini-3-flash-preview"
    assert saved["model_id"] == 1010
    assert writes[0][2] == PREF_TYPE_DEFAULT_LLM_MODEL


def test_sync_image_world_default_tries_both_modes(monkeypatch):
    from api import script_writer as sw
    from config.constant import MediaGenerationMode

    saved = []
    monkeypatch.setattr(
        sw.MediaGenerationPreferenceService,
        "get_profile",
        lambda *a, **k: {"ratio": "9:16"},
    )
    monkeypatch.setattr(
        sw.MediaGenerationPreferenceService,
        "save_profile",
        lambda user_id, world_id, surface, media_type, mode, profile: (
            saved.append(mode) or dict(profile)
        ),
    )
    sw._sync_image_model_to_media_pref_world_default("1", "101", 33)
    assert MediaGenerationMode.TEXT_TO_IMAGE in saved
    assert MediaGenerationMode.IMAGE_EDIT in saved
