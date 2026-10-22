"""Storyboard UI 五槽位偏好同步：读取不落库 + None 槽位运行时兜底。

事故背景：_storyboard_media_preferences_sync 原先经 get_profile 默认
initialize=True，首次 GET /media-preferences 会把 default_model（旧口径
sort_order 第一 = LTX2.3）固化进 user_preferences，从此隐身模式/新浏览器
都命中该记录，前端性价比档兜底（59009cf3）被短路。
"""

from types import SimpleNamespace
from unittest.mock import patch

from config.constant import (
    MediaGenerationErrorCode,
    MediaGenerationMode,
    MediaGenerationSurface,
    MediaGenerationType,
)
from model.storyboard import StoryboardModel
from services.media_generation_preference_service import (
    MediaGenerationPreferenceError,
    MediaGenerationPreferenceService,
)


def _storyboard(config_json=None):
    return SimpleNamespace(
        id=15,
        user_id=6,
        world_id=12,
        workflow_ratio=None,
        to_dict=lambda: {"config_json": config_json or {}},
    )


def _fake_config(task_id=34, key="minimax_h3_image_to_video", name="MiniMax H3"):
    return SimpleNamespace(id=task_id, key=key, name=name)


def test_storyboard_ui_preferences_read_does_not_initialize():
    """无持久化偏好时读取不落库：五槽位返回 None、不 patch config_json。"""
    from api.storyboard import _storyboard_media_preferences_sync

    calls = []
    patch_calls = []

    def fake_get_profile(user_id, world_id, surface, media_type, mode, **kwargs):
        calls.append(
            {
                "surface": surface,
                "initialize": kwargs.get("initialize"),
            }
        )
        assert kwargs.get("initialize") is False
        return None

    sb = _storyboard()
    with patch.object(
        MediaGenerationPreferenceService, "get_profile", side_effect=fake_get_profile
    ), patch.object(
        StoryboardModel, "patch_config_json", side_effect=lambda *a: patch_calls.append(a)
    ):
        profiles = _storyboard_media_preferences_sync(sb)

    assert len(calls) == 5
    assert all(c["surface"] == MediaGenerationSurface.STORYBOARD_UI for c in calls)
    assert all(v is None for v in profiles.values())
    assert patch_calls == []


def test_storyboard_ui_preferences_config_json_still_wins():
    """config_json 已保存的选择仍优先返回并回写（既有行为保持）。"""
    from api.storyboard import _storyboard_media_preferences_sync

    sb = _storyboard({"selectedImageToVideoTaskId": 20})
    patch_calls = []

    def fake_validate_model(task_id, media_type, mode, **kwargs):
        return _fake_config(20, "ltx2_3_image_to_video", "LTX2.3")

    with patch.object(
        MediaGenerationPreferenceService,
        "get_profile",
        side_effect=lambda *a, **k: None,
    ), patch.object(
        MediaGenerationPreferenceService, "validate_model", side_effect=fake_validate_model
    ), patch.object(
        StoryboardModel, "patch_config_json", side_effect=lambda *a: patch_calls.append(a)
    ):
        profiles = _storyboard_media_preferences_sync(sb)

    assert profiles["video.image_to_video"]["task_id"] == 20
    assert profiles["image.text_to_image"] is None
    fields = patch_calls[0][1]
    assert fields == {"selectedImageToVideoTaskId": 20}


def test_generation_snapshots_fill_none_slot_with_runtime_default():
    """提交冻结时 None 槽位按运行时默认（性价比档）解析，不落库。"""
    from api.storyboard import _storyboard_generation_snapshots_sync

    snapshot_calls = []

    def fake_default_model(media_type, mode):
        return _fake_config(34)

    def fake_build_snapshot(profile, surface, media_type, mode, **kwargs):
        snapshot_calls.append({"slot": f"{media_type}.{mode}", "task_id": profile["task_id"]})
        return {"task_id": profile["task_id"]}

    with patch.object(
        MediaGenerationPreferenceService,
        "get_profile",
        side_effect=lambda *a, **k: None,
    ), patch.object(
        MediaGenerationPreferenceService, "default_model", side_effect=fake_default_model
    ), patch.object(
        MediaGenerationPreferenceService, "build_snapshot", side_effect=fake_build_snapshot
    ):
        snapshots = _storyboard_generation_snapshots_sync(_storyboard())

    assert len(snapshot_calls) == 5
    assert all(c["task_id"] == 34 for c in snapshot_calls)
    assert set(snapshots.keys()) == {
        "image.text_to_image",
        "image.image_edit",
        "video.text_to_video",
        "video.image_to_video",
        "video.reference_to_video",
    }


def test_resolve_snapshot_none_slot_runtime_default():
    """_resolve_storyboard_generation_snapshot_sync 无显式 task_id 且无偏好时
    走运行时默认，不因 None profile 抛 MODEL_REQUIRED。"""
    from api.storyboard import _resolve_storyboard_generation_snapshot_sync

    captured = {}

    def fake_default_model(media_type, mode):
        return _fake_config(34)

    def fake_build_snapshot(profile, surface, media_type, mode, **kwargs):
        captured["task_id"] = profile["task_id"]
        captured["source"] = kwargs.get("model_source")
        return {"task_id": profile["task_id"]}

    with patch.object(
        MediaGenerationPreferenceService,
        "get_profile",
        side_effect=lambda *a, **k: None,
    ), patch.object(
        MediaGenerationPreferenceService, "default_model", side_effect=fake_default_model
    ), patch.object(
        MediaGenerationPreferenceService, "build_snapshot", side_effect=fake_build_snapshot
    ):
        _resolve_storyboard_generation_snapshot_sync(
            _storyboard(),
            user_id=6,
            media_type=MediaGenerationType.VIDEO,
            mode=MediaGenerationMode.IMAGE_TO_VIDEO,
            explicit_task_id=None,
        )

    assert captured["task_id"] == 34
    assert captured["source"] == "storyboard_config"


def test_runtime_default_profile_raises_when_no_model():
    """无任何可用模型时抛 MODEL_REQUIRED（与原 get_profile 行为一致）。"""
    from api.storyboard import _runtime_default_profile_sync

    with patch.object(
        MediaGenerationPreferenceService, "default_model", side_effect=lambda *a: None
    ):
        try:
            _runtime_default_profile_sync(
                MediaGenerationType.VIDEO, MediaGenerationMode.IMAGE_TO_VIDEO
            )
        except MediaGenerationPreferenceError as exc:
            assert exc.code == MediaGenerationErrorCode.MODEL_REQUIRED
        else:
            raise AssertionError("expected MediaGenerationPreferenceError")
