from pathlib import Path


SOURCE = (Path(__file__).parents[2] / "api" / "storyboard.py").read_text(encoding="utf-8")


def test_video_type_switch_route_is_non_blocking_and_maps_conflict():
    assert "@router.put('/scene/{scene_id}/video-type')" in SOURCE
    assert "await asyncio.to_thread(\n            switch_storyboard_scene_video_type" in SOURCE
    assert "except StoryboardVideoTypeConflict" in SOURCE
    assert "status_code=409" in SOURCE


def test_video_type_switch_route_maps_validation_and_missing_scene():
    assert "except StoryboardVideoTypeValidationError" in SOURCE
    assert "except StoryboardVideoTypeNotFound" in SOURCE
