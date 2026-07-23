"""Unit tests for storyboard scene video_type resolution."""
from config.unified_config import SceneVideoType
from services.storyboard_scene_type import (
    count_speaking_characters,
    resolve_scene_video_type,
)


def test_count_speaking_ignores_empty_and_narration():
    dialogues = [
        {"character_id": None, "text": "旁白"},
        {"character_id": 1, "text": "你好"},
        {"character_id": 1, "text": "再见"},
        {"character_id": 2, "text": ""},
    ]
    count, sole = count_speaking_characters(dialogues)
    assert count == 1
    assert sole == 1


def test_multi_speaker_forced_video():
    shot = {
        "presentation": "digital_human",
        "shot_type": "近景",
        "action": "两人对话",
    }
    dialogues = [
        {"character_id": 1, "text": "A"},
        {"character_id": 2, "text": "B"},
    ]
    video_type, meta = resolve_scene_video_type(shot, dialogues)
    assert video_type == SceneVideoType.VIDEO
    assert meta["speaker_count"] == 2
    assert meta["presentation_reason"] == "multi_speaker"


def test_single_speaker_llm_digital_human():
    shot = {
        "presentation": "digital_human",
        "shot_type": "中景",
        "action": "角色说话",
    }
    dialogues = [{"character_id": 9, "text": "你好"}]
    video_type, meta = resolve_scene_video_type(shot, dialogues)
    assert video_type == SceneVideoType.DIGITAL_HUMAN
    assert meta["presentation_source"] == "llm"
    assert meta["speaker_character_id"] == 9


def test_single_speaker_close_shot_heuristic():
    shot = {"shot_type": "特写", "action": "微笑开口"}
    dialogues = [{"character_id": 3, "text": "台词"}]
    video_type, meta = resolve_scene_video_type(shot, dialogues)
    assert video_type == SceneVideoType.DIGITAL_HUMAN
    assert meta["presentation_source"] == "heuristic"


def test_single_speaker_strong_action_stays_video():
    shot = {
        "presentation": "digital_human",
        "shot_type": "近景",
        "action": "角色边打斗边喊话",
        "description": "激烈打斗场面",
    }
    dialogues = [{"character_id": 1, "text": "接招"}]
    video_type, meta = resolve_scene_video_type(shot, dialogues)
    assert video_type == SceneVideoType.VIDEO
    assert meta["presentation_reason"] == "strong_action"


def test_no_dialogue_is_video():
    video_type, meta = resolve_scene_video_type({"shot_type": "近景"}, [])
    assert video_type == SceneVideoType.VIDEO
    assert meta["presentation_reason"] == "no_single_speaker"
