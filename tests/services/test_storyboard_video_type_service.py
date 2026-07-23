import pytest

from services.storyboard_video_type_service import (
    StoryboardVideoTypeConflict,
    StoryboardVideoTypeValidationError,
    decide_selected_video_after_switch,
    validate_video_type_switch,
)


def _asset(asset_id, *, status, video_type, result_url=None):
    return {
        "id": asset_id,
        "status": status,
        "video_type": video_type,
        "result_url": result_url,
    }


def test_preserves_completed_selected_video_when_switching_to_video():
    selected = _asset(10, status=2, video_type="digital_human", result_url="/old.mp4")

    result = decide_selected_video_after_switch("video", selected, [])

    assert result == {
        "selected_video_id": 10,
        "video_url": "/old.mp4",
        "old_task_detached": False,
    }


def test_detaches_running_old_mode_and_restores_latest_completed_video():
    selected = _asset(12, status=1, video_type="digital_human")
    candidates = [
        _asset(11, status=2, video_type="digital_human", result_url="/latest.mp4"),
        _asset(9, status=2, video_type="video", result_url="/older.mp4"),
    ]

    result = decide_selected_video_after_switch("video", selected, candidates)

    assert result == {
        "selected_video_id": 11,
        "video_url": "/latest.mp4",
        "old_task_detached": True,
    }


def test_detaches_running_old_mode_without_completed_fallback():
    selected = _asset(12, status=0, video_type="digital_human")

    result = decide_selected_video_after_switch("video", selected, [])

    assert result == {
        "selected_video_id": None,
        "video_url": None,
        "old_task_detached": True,
    }


def test_preserves_running_asset_when_it_matches_target_mode():
    selected = _asset(12, status=1, video_type="video")

    result = decide_selected_video_after_switch("video", selected, [])

    assert result["selected_video_id"] == 12
    assert result["old_task_detached"] is False


def test_rejects_concurrent_type_change():
    with pytest.raises(StoryboardVideoTypeConflict):
        validate_video_type_switch(
            current_type="video",
            target_type="digital_human",
            expected_type="digital_human",
            speaker_count=1,
        )


def test_rejects_multi_speaker_digital_human_switch():
    with pytest.raises(StoryboardVideoTypeValidationError, match="单个说话角色"):
        validate_video_type_switch(
            current_type="video",
            target_type="digital_human",
            expected_type="video",
            speaker_count=2,
        )


def test_rejects_image_as_switch_target():
    with pytest.raises(StoryboardVideoTypeValidationError, match="video 或 digital_human"):
        validate_video_type_switch(
            current_type="video",
            target_type="image",
            expected_type="video",
            speaker_count=0,
        )
