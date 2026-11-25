"""
Storyboard scene video_type resolution for script split.

Rules (current policy):
- Split NEVER auto-assigns digital_human (lip-sync): every inferred scene is video.
  Lip-sync is opt-in only — the user switches a scene manually in the storyboard UI
  (video-type switch via services/storyboard_video_type_service.py).
- An explicitly stored ``video_type`` (a user's manual choice carried through the
  workflow round-trip, see api/storyboard_conversion.py) is still honored, so a
  manual digital_human choice survives re-conversion.
- Hard rules unchanged: no dialogue / multi-speaker / speaker not visible /
  multi-character frame / strong action → video (also override explicit type,
  same as before).
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


def _character_ref(value: Any) -> str:
    """Normalize a character reference from ``characters_present``."""
    if isinstance(value, dict):
        value = value.get("character_id") or value.get("id")
    return _norm_text(value)


def _visible_character_ids(shot: dict) -> List[str]:
    """Return distinct, non-empty character IDs that are visible in the shot."""
    raw_characters = shot.get("characters_present") or []
    if not isinstance(raw_characters, (list, tuple)):
        return []

    result: List[str] = []
    seen = set()
    for raw_character in raw_characters:
        character_id = _character_ref(raw_character)
        if not character_id or character_id in seen:
            continue
        seen.add(character_id)
        result.append(character_id)
    return result


def _source_speaking_character_ids(shot: dict) -> List[str]:
    """Read speaking IDs before DB-ID mapping so visibility can be compared safely."""
    raw_dialogues = shot.get("dialogue") or shot.get("dialogues") or []
    if isinstance(raw_dialogues, dict):
        raw_dialogues = [raw_dialogues]
    if not isinstance(raw_dialogues, (list, tuple)):
        return []

    result: List[str] = []
    seen = set()
    for dialogue in raw_dialogues:
        if not isinstance(dialogue, dict) or not _norm_text(dialogue.get("text")):
            continue
        character_id = _character_ref(dialogue.get("character_id"))
        if not character_id or character_id in seen:
            continue
        seen.add(character_id)
        result.append(character_id)
    return result


def _explicit_video_type(shot: dict) -> Optional[str]:
    """Read the explicitly stored ``video_type`` (user's manual choice).

    Only explicit storage is trusted. The LLM split output's ``presentation``
    field is intentionally ignored: split must not auto-produce lip-sync scenes
    (对口型仅支持用户手动切换).
    """
    raw = shot.get("video_type")
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
    visible_character_ids = _visible_character_ids(shot)
    source_speaker_ids = _source_speaking_character_ids(shot)
    meta: Dict[str, Any] = {
        "speaker_count": speaker_count,
        "speaker_character_id": sole_speaker,
        "visible_character_count": len(visible_character_ids),
        "presentation_source": "rule",
    }

    # Hard rules first — multi-speaker / no speaker never digital_human.
    if speaker_count != 1:
        meta["presentation_reason"] = (
            "no_single_speaker" if speaker_count == 0 else "multi_speaker"
        )
        return SceneVideoType.VIDEO, meta

    # Lip-sync consumes one face image: the frame must contain exactly one
    # visible character, and that same character must be the sole speaker.
    # This rejects object/animal inserts with off-screen narration as well as
    # one-speaker dialogue shots that still show listeners or other people.
    if len(visible_character_ids) != 1:
        meta["presentation_reason"] = (
            "no_visible_character"
            if not visible_character_ids
            else "multi_character_frame"
        )
        return SceneVideoType.VIDEO, meta

    if len(source_speaker_ids) != 1:
        meta["presentation_reason"] = (
            "speaker_visibility_unknown"
            if not source_speaker_ids
            else "multi_speaker"
        )
        return SceneVideoType.VIDEO, meta

    if source_speaker_ids[0] != visible_character_ids[0]:
        meta["presentation_reason"] = "speaker_not_visible"
        return SceneVideoType.VIDEO, meta

    if _has_strong_action(shot):
        meta["presentation_source"] = "heuristic"
        meta["presentation_reason"] = "strong_action"
        return SceneVideoType.VIDEO, meta

    # 显式存储类型优先采信：用户手动切换的对口型经反向转换往返保真
    # （shot['video_type'] 透传见 api/storyboard_conversion.py）。
    # 拆分路径的 shot 无 video_type 字段，此处不会命中。
    explicit = _explicit_video_type(shot)
    if explicit == SceneVideoType.DIGITAL_HUMAN:
        meta["presentation_source"] = "explicit"
        meta["presentation_reason"] = "explicit_digital_human"
        return SceneVideoType.DIGITAL_HUMAN, meta

    if explicit == SceneVideoType.VIDEO:
        meta["presentation_source"] = "explicit"
        meta["presentation_reason"] = "explicit_video"
        return SceneVideoType.VIDEO, meta

    # 拆分关闭自动对口型：单说话人对白近景也一律视频模式，
    # 对口型仅支持用户在分镜详情手动切换（video-type switch）。
    if _is_close_talking_shot(shot) or not _norm_text(shot.get("shot_type")):
        meta["presentation_source"] = "heuristic"
        meta["presentation_reason"] = "single_speaker_close_video"
        return SceneVideoType.VIDEO, meta

    # Single speaker with dialogue but wide/action framing → video.
    meta["presentation_source"] = "heuristic"
    meta["presentation_reason"] = "single_speaker_non_close"
    return SceneVideoType.VIDEO, meta
