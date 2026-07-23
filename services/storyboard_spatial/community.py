"""Community-edition compatibility layer for storyboard spatial data.

The enterprise implementation owns episode-level spatial worlds, camera
projection, and prompt context enrichment. This module keeps legacy v1
`spatial_layout` payloads readable in community edition without enabling the
quality/effect-mode spatial engine.
"""

from typing import Any, Dict, List, Optional, Tuple

from .exceptions import StoryboardEnterpriseFeatureRequired


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _slot_visibility(item: Dict[str, Any]) -> str:
    return str(item.get("visibility") or "visible").strip().lower()


def _is_visible_spatial_item(item: Dict[str, Any]) -> bool:
    return _slot_visibility(item) in ("visible", "partial")


def build_spatial_world_index(parsed_or_prompt: Dict[str, Any]) -> Dict[str, Any]:
    raise StoryboardEnterpriseFeatureRequired()


def derive_screen_projection(
    entity: Dict[str, Any],
    camera_pose: Dict[str, Any],
    world_index: Dict[str, Any],
) -> Dict[str, Any]:
    raise StoryboardEnterpriseFeatureRequired()


def build_spatial_prompt_context(
    spatial_layout: Dict[str, Any],
    spatial_world: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    visible: List[Dict[str, Any]] = []
    hidden: List[Dict[str, Any]] = []

    def append_entity(raw: Dict[str, Any], *, container_name: str = "") -> None:
        if not isinstance(raw, dict):
            return
        name = _first_non_empty(raw.get("name"), raw.get("prop_name"), raw.get("label"))
        if not name:
            return
        entity = {
            "name": name,
            "slot": _first_non_empty(raw.get("slot"), raw.get("anchor_id"), raw.get("slot_id"), raw.get("screen_position"), raw.get("position")),
            "screen_position": _first_non_empty(raw.get("screen_position"), raw.get("position")),
            "raw_screen_position": _first_non_empty(raw.get("screen_position"), raw.get("position")),
            "derived_screen_position": None,
            "projection": None,
            "pose": _first_non_empty(raw.get("pose")),
            "visibility": _slot_visibility(raw),
            "framing_role": _first_non_empty(raw.get("framing_role")),
            "container": container_name,
            "occupant_type": _first_non_empty(raw.get("occupant_type"), "character"),
            "character_id": raw.get("character_id") or raw.get("occupant_character_id"),
            "db_id": raw.get("character_db_id") or raw.get("db_id"),
            "space_unit_id": raw.get("space_unit_id"),
            "anchor_id": raw.get("anchor_id"),
        }
        if _is_visible_spatial_item(raw):
            visible.append(entity)
        else:
            hidden.append(entity)

    spatial_layout = spatial_layout if isinstance(spatial_layout, dict) else {}
    for container in _as_list(spatial_layout.get("containers")):
        if not isinstance(container, dict):
            continue
        container_name = _first_non_empty(container.get("name"), container.get("area"))
        for slot in _as_list(container.get("slots")):
            append_entity(slot, container_name=container_name)

    for position in _as_list(spatial_layout.get("loose_positions")):
        append_entity(position)

    return {
        "visible_entities": visible,
        "hidden_entities": hidden,
        "camera_pose": {},
        "world_index": {"spatial_world": {}, "space_units": {}, "anchors": {}, "frames": {}},
    }


def repair_spatial_layout_continuity(parsed_data: Dict[str, Any]) -> Dict[str, Any]:
    # Community edition keeps parser compatibility but does not run the
    # enterprise spatial continuity engine.
    return parsed_data
