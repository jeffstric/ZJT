import asyncio
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


def test_storyboard_video_agent_builds_task_scoped_preferences_without_persisting(monkeypatch):
    """Storyboard Agent 视频偏好只认界面显式参数，不读写 Marketing 共享偏好。"""
    from api import script_writer, storyboard
    from config.unified_config import DriverKey, UnifiedConfigRegistry

    monkeypatch.setattr(
        script_writer,
        "get_video_preferences",
        lambda user_id, world_id: (_ for _ in ()).throw(
            AssertionError("storyboard must not read marketing video preferences")
        ),
    )
    monkeypatch.setattr(
        script_writer,
        "set_video_preferences",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("task-scoped storyboard settings must not be persisted")
        ),
    )

    def _fake_get_by_id(task_id):
        tid = int(task_id)
        if tid == 27:
            return SimpleNamespace(name="Grok", key="grok_image_to_video")
        if tid == 23:
            return SimpleNamespace(
                name="Seedance 2.0",
                key=DriverKey.SEEDANCE_2_0_IMAGE_TO_VIDEO,
            )
        return None

    monkeypatch.setattr(
        UnifiedConfigRegistry,
        "get_by_id",
        staticmethod(_fake_get_by_id),
    )
    # 强制非社区版，便于断言 enable_face_mask
    monkeypatch.setattr(storyboard.Edition, "is_community", staticmethod(lambda: False))

    # 非 Seedance：即使传入 enable_face_mask=True 也强制 false
    preferences = asyncio.run(
        storyboard._build_storyboard_agent_video_preferences(
            user_id=7,
            world_id=99,
            storyboard=SimpleNamespace(workflow_ratio="9:16"),
            image_mode="first_last_frame",
            duration_seconds=5,
            video_resolution="720P",
            video_task_id=27,
            enable_face_mask=True,
        )
    )
    assert preferences == {
        "ratio": "9:16",
        "enable_face_mask": False,
        "image_mode": "first_last_frame",
        "duration": 5,
        "resolution": "720P",
        "task_id": 27,
        "model_name": "Grok",
    }

    # Seedance 2.0 + 显式勾选：保留 true
    seedance_prefs = asyncio.run(
        storyboard._build_storyboard_agent_video_preferences(
            user_id=7,
            world_id=99,
            storyboard=SimpleNamespace(workflow_ratio="9:16"),
            image_mode="first_last_frame",
            duration_seconds=5,
            video_resolution="720P",
            video_task_id=23,
            enable_face_mask=True,
        )
    )
    assert seedance_prefs["enable_face_mask"] is True
    assert seedance_prefs["task_id"] == 23
    assert seedance_prefs["model_name"] == "Seedance 2.0"

    api_source = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")
    route_start = api_source.index("async def scene_ai_chat(")
    route_end = api_source.index("@router.get('/scene/{scene_id}/ai-chat/history')", route_start)
    route_source = api_source[route_start:route_end]
    assert "await _build_storyboard_agent_video_preferences(" in route_source
    assert "video_preferences=video_preferences" in route_source
    assert "video_task_id=video_task_id" in route_source
    assert "enable_face_mask=" in route_source
