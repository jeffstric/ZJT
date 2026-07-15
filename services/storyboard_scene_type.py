"""
Storyboard scene video_type resolution for script split.

Rules (phase 1):
- No dialogue / narration-only / multi-speaker dialogues → video
- Exactly one speaking character → digital_human candidate
  (LLM presentation=digital_human or pure-dialogue heuristic)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.unified_config import SceneVideoType


# Shot types that lean toward talking-head / lip-sync.
_CLOSE_SHOT_HINTS = (
    "近景",
    "特写",
    "中近景",
    "大特写",
    "close-up",
    "closeup",
    "medium close",
    "MCU",
    "CU",
    "ECU",
)

# Strong action signals → keep image-to-video even with single speaker.
_ACTION_HINTS = (
    "打斗",
    "追逐",
    "奔",
    "跑",
    "打",
    "战",
    "爆炸",
    "飞",
    "跳",
    "扑",
    "击",
    "射击",
    "武打",
    "动作戏",
    "fight",
    "chase",
    "run",
    "explode",
)


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def count_speaking_characters(dialogues: Sequence[dict]) -> Tuple[int, Optional[Any]]:
    """
    Count distinct speaking character_ids among non-empty dialogue lines.

    Narration (missing/null character_id) is ignored for speaker count.
    Returns (speaker_count, sole_speaker_id_or_None).
    """
    speakers = []
    seen = set()
    for dialogue in dialogues or []:
        text = _norm_text(dialogue.get("text"))
        if not text:
            continue
        cid = dialogue.get("character_id")
        if cid is None or cid == "" or cid == 0:
            continue
        key = str(cid)
        if key not in seen:
            seen.add(key)
            speakers.append(cid)
    if len(speakers) == 1:
        return 1, speakers[0]
    return len(speakers), None


def _llm_presentation(shot: dict) -> Optional[str]:
    raw = shot.get("presentation") or shot.get("video_type")
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value in ("digital_human", "lip_sync", "lip-sync", "对口型", "数字人"):
        return SceneVideoType.DIGITAL_HUMAN
    if value in ("video", "image", "i2v", "视频", "图生视频"):
        return SceneVideoType.VIDEO
    return None


def _text_blob(shot: dict) -> str:
    parts = [
        shot.get("action"),
        shot.get("description"),
        shot.get("scene_detail"),
        shot.get("narrative_purpose"),
        shot.get("camera_movement"),
    ]
    return " ".join(_norm_text(p) for p in parts if _norm_text(p)).lower()


def _is_close_talking_shot(shot: dict) -> bool:
    shot_type = _norm_text(shot.get("shot_type")).lower()
    camera_angle = _norm_text(shot.get("camera_angle")).lower()
    combined = f"{shot_type} {camera_angle}"
    return any(hint.lower() in combined for hint in _CLOSE_SHOT_HINTS)


def _has_strong_action(shot: dict) -> bool:
    blob = _text_blob(shot)
    if not blob:
        return False
    return any(hint.lower() in blob for hint in _ACTION_HINTS)


def resolve_scene_video_type(
    shot: Optional[dict],
    dialogues: Sequence[dict],
) -> Tuple[str, Dict[str, Any]]:
    """
    Resolve storyboard_scene.video_type and metadata for video_config.

    Returns:
        (video_type, meta) where meta includes presentation_source / speaker_count / ...
    """
    shot = shot or {}
    speaker_count, sole_speaker = count_speaking_characters(dialogues)
    meta: Dict[str, Any] = {
        "speaker_count": speaker_count,
        "speaker_character_id": sole_speaker,
        "presentation_source": "rule",
    }

    # Hard rules first — multi-speaker / no speaker never digital_human.
    if speaker_count != 1:
        meta["presentation_reason"] = (
            "no_single_speaker" if speaker_count == 0 else "multi_speaker"
        )
        return SceneVideoType.VIDEO, meta

    if _has_strong_action(shot):
        meta["presentation_source"] = "heuristic"
        meta["presentation_reason"] = "strong_action"
        return SceneVideoType.VIDEO, meta

    llm = _llm_presentation(shot)
    if llm == SceneVideoType.DIGITAL_HUMAN:
        meta["presentation_source"] = "llm"
        meta["presentation_reason"] = "llm_digital_human"
        return SceneVideoType.DIGITAL_HUMAN, meta

    if llm == SceneVideoType.VIDEO:
        meta["presentation_source"] = "llm"
        meta["presentation_reason"] = "llm_video"
        return SceneVideoType.VIDEO, meta

    # Heuristic: single speaker + close shot (or no shot_type) and no strong action.
    if _is_close_talking_shot(shot) or not _norm_text(shot.get("shot_type")):
        meta["presentation_source"] = "heuristic"
        meta["presentation_reason"] = "single_speaker_dialogue"
        return SceneVideoType.DIGITAL_HUMAN, meta

    # Single speaker with dialogue but wide/action framing → video.
    meta["presentation_source"] = "heuristic"
    meta["presentation_reason"] = "single_speaker_non_close"
    return SceneVideoType.VIDEO, meta
