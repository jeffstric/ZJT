import asyncio


def test_sync_script_split_model_preference_saves_world_selection(monkeypatch):
    from api import storyboard

    calls = []
    monkeypatch.setattr(
        storyboard.UserPreferencesModel,
        "upsert",
        staticmethod(lambda *args: calls.append(args) or 1),
    )
    selection = {
        "model": "deepseek-v4-pro",
        "model_id": 1008,
        "vendor_id": 10,
    }

    saved, warning = asyncio.run(
        storyboard._sync_script_split_model_preference(
            7,
            99,
            {"selectedScriptSplitLlmModel": selection},
        )
    )

    assert saved is True
    assert warning is None
    assert calls == [("7", "99", "script_split_llm_model", selection)]


def test_sync_script_split_model_preference_skips_unrelated_config(monkeypatch):
    from api import storyboard

    calls = []
    monkeypatch.setattr(
        storyboard.UserPreferencesModel,
        "upsert",
        staticmethod(lambda *args: calls.append(args) or 1),
    )

    saved, warning = asyncio.run(
        storyboard._sync_script_split_model_preference(7, 99, {"selectedImageTaskId": 3})
    )

    assert saved is None
    assert warning is None
    assert calls == []


def test_sync_script_split_model_preference_reports_failure(monkeypatch):
    from api import storyboard

    def fail(*args):
        raise RuntimeError("preference db unavailable")

    monkeypatch.setattr(storyboard.UserPreferencesModel, "upsert", staticmethod(fail))

    saved, warning = asyncio.run(
        storyboard._sync_script_split_model_preference(
            7,
            99,
            {"selectedScriptSplitLlmModel": "deepseek-v4-pro"},
        )
    )

    assert saved is False
    assert "偏好同步失败" in warning
