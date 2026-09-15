"""参考生视频：把同一分镜组内的短镜头贪婪合并到模型单段上限。"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _shot_duration(shot: Dict[str, Any]) -> float:
    return max(0.0, _safe_float(shot.get("duration"), 0.0))


def _shot_prompt_text(shot: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("description", "scene_detail", "action"):
        text = str(shot.get(key) or "").strip()
        if text:
            parts.append(text)
    movement = str(shot.get("camera_movement") or "").strip()
    if movement:
        parts.append(f"镜头运动：{movement}")
    purpose = str(shot.get("narrative_purpose") or "").strip()
    if purpose:
        parts.append(f"叙事目的：{purpose}")
    return "，".join(parts)


def _dialogue_list(shot: Dict[str, Any]) -> List[Any]:
    raw = shot.get("dialogue")
    if raw is None:
        raw = shot.get("dialogues")
    return list(raw) if isinstance(raw, list) else []


def _union_keep_order(left: Any, right: Any) -> List[Any]:
    out: List[Any] = []
    seen = set()
    for item in list(left or []) + list(right or []):
        marker = str(item)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def _format_span(start: float, end: float) -> str:
    def _fmt(value: float) -> str:
        if abs(value - round(value)) < 1e-6:
            return str(int(round(value)))
        return f"{value:.1f}".rstrip("0").rstrip(".")

    return f"{_fmt(start)}~{_fmt(end)}S"


def pack_shots_for_reference_video(
    shots: List[Dict[str, Any]],
    max_duration: float,
) -> List[Dict[str, Any]]:
    """同一组内贪婪合并：再并入下一镜会超过 max_duration 则切开。

    单镜已超过上限时原样保留（无法再拆）。空 duration 的镜单独成条以免拖垮合并。
    """
    cap = max(0.1, float(max_duration or 0))
    packed: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    segments: List[Dict[str, Any]] = []

    def flush() -> None:
        nonlocal current, segments
        if current is None:
            return
        packed.append(_flatten_packed_shot(current, segments))
        current = None
        segments = []

    for shot in shots or []:
        if not isinstance(shot, dict):
            continue
        duration = _shot_duration(shot)
        if current is not None and duration > 0 and (current["_pack_duration"] + duration) > cap + 1e-6:
            flush()
        if current is None:
            current = copy.deepcopy(shot)
            current["_pack_duration"] = duration
            segments = [{
                "duration": duration,
                "prompt": _shot_prompt_text(shot),
            }]
            continue
        current["_pack_duration"] = float(current["_pack_duration"]) + duration
        current["dialogue"] = _dialogue_list(current) + _dialogue_list(shot)
        if "dialogues" in current:
            current.pop("dialogues", None)
        current["characters_present"] = _union_keep_order(
            current.get("characters_present"), shot.get("characters_present"),
        )
        current["props_present"] = _union_keep_order(
            current.get("props_present"), shot.get("props_present"),
        )
        segments.append({
            "duration": duration,
            "prompt": _shot_prompt_text(shot),
        })
    flush()
    return packed


def pack_parsed_for_reference_video(
    parsed_data: Dict[str, Any],
    max_duration: float,
) -> Dict[str, Any]:
    """只合并每个 shot_group 内部的 shots，不跨组。"""
    if not isinstance(parsed_data, dict):
        return parsed_data
    groups = []
    for group in parsed_data.get("shot_groups") or []:
        if not isinstance(group, dict):
            continue
        packed_group = dict(group)
        packed_group["shots"] = pack_shots_for_reference_video(
            group.get("shots") or [], max_duration,
        )
        groups.append(packed_group)
    out = dict(parsed_data)
    out["shot_groups"] = groups
    return out


def _flatten_packed_shot(shot: Dict[str, Any], segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = dict(shot)
    total = float(out.pop("_pack_duration", 0) or 0)
    if total <= 0:
        total = sum(float(seg.get("duration") or 0) for seg in segments)
    out["duration"] = round(total, 3) if total else out.get("duration")
    if len(segments) > 1:
        cursor = 0.0
        parts = []
        for index, seg in enumerate(segments, start=1):
            dur = max(0.0, float(seg.get("duration") or 0))
            end = cursor + dur
            text = str(seg.get("prompt") or "").strip() or "（无描述）"
            parts.append(f"镜头{index}：{_format_span(cursor, end)}，{text}")
            cursor = end
        out["description"] = "；".join(parts)
        out["scene_detail"] = ""
        out["action"] = ""
        out["camera_movement"] = ""
        out["narrative_purpose"] = ""
    return out
