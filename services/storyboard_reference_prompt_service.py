"""
Storyboard reference image matching helpers.

Keep this module pure: API routes can call it from async handlers without DB work,
and tests can validate prompt/reference behavior without booting the server.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional


ROLE_TAG_RE = re.compile(r"【【([^】]+)】】")
PROP_TAG_RE = re.compile(r"〖〖([^〗]+)〗〗")


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _clean_name(name: Any) -> str:
    return str(name or "").strip()


def _dedupe_keep_order(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        key = _clean_name(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def _extract_tagged_names(text: str, pattern: re.Pattern[str]) -> List[str]:
    return _dedupe_keep_order(match.group(1) for match in pattern.finditer(text or ""))


def _plain_text_contains_name(text: str, name: str) -> bool:
    if not text or not name:
        return False
    return name in text


def _reference_url(asset: Dict[str, Any]) -> str:
    if not asset:
        return ""
    for key in ("selected_reference_image", "reference_image", "image_url", "avatar", "pic", "url"):
        value = asset.get(key)
        if value:
            return str(value)

    refs = asset.get("reference_images")
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except Exception:
            refs = []
    if isinstance(refs, list):
        for item in refs:
            if isinstance(item, str) and item:
                return item
            if isinstance(item, dict):
                for key in ("url", "file_url", "image_url", "reference_image"):
                    if item.get(key):
                        return str(item[key])
    return ""


def _asset_by_name(assets: Iterable[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    target = _clean_name(name)
    for asset in assets or []:
        if _clean_name(asset.get("name")) == target:
            return asset
    return None


def _asset_by_id_or_name(assets: Iterable[Dict[str, Any]], candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    candidate_name = _clean_name(candidate.get("name"))
    candidate_ids = {
        str(candidate.get("id") or ""),
        str(candidate.get("db_id") or ""),
        str(candidate.get("props_db_id") or ""),
        str(candidate.get("character_db_id") or ""),
        str(candidate.get("location_db_id") or ""),
    }
    candidate_ids.discard("")

    for asset in assets or []:
        asset_ids = {
            str(asset.get("id") or ""),
            str(asset.get("db_id") or ""),
            str(asset.get("props_db_id") or ""),
            str(asset.get("character_db_id") or ""),
            str(asset.get("location_db_id") or ""),
        }
        asset_ids.discard("")
        if candidate_ids and asset_ids and candidate_ids.intersection(asset_ids):
            return asset
        if candidate_name and _clean_name(asset.get("name")) == candidate_name:
            return asset
    return None


def _prompt_text(prompt_json: Dict[str, Any], video_prompt: str = "") -> str:
    parts = [
        prompt_json.get("scene_desc") or "",
        prompt_json.get("opening_frame_description") or "",
        prompt_json.get("image_prompt") or "",
        video_prompt or prompt_json.get("video_prompt") or "",
    ]
    return "\n".join(str(part) for part in parts if part)


def _add_reference_item(items: List[Dict[str, str]], asset_type: str, name: str, url: str) -> None:
    if not name or not url:
        return
    if any(item["url"] == url or (item["type"] == asset_type and item["name"] == name) for item in items):
        return
    items.append({"type": asset_type, "name": name, "url": url})


def build_storyboard_reference_items(
    *,
    prompt_json: Any,
    video_prompt: str = "",
    characters: Optional[List[Dict[str, Any]]] = None,
    props: Optional[List[Dict[str, Any]]] = None,
    location: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Return minimal ordered reference items for a storyboard scene.

    Matching rules intentionally mirror the shot frame node:
    - characters come from `【【角色名】】` in current image/video prompt text;
    - props come from `〖〖道具名〗〗`, and fall back to plain name mentions in prompt text;
    - `character_desc` and historical `prompt_json.props` do not add references by themselves;
    - at most one scene/location reference is appended after matched roles/props.
    """
    prompt = _as_dict(prompt_json)
    text = _prompt_text(prompt, video_prompt)
    items: List[Dict[str, str]] = []
    characters = characters or []
    props = props or []

    for name in _extract_tagged_names(text, ROLE_TAG_RE):
        asset = _asset_by_name(characters, name)
        _add_reference_item(items, "角色", name, _reference_url(asset or {}))

    prop_names = _extract_tagged_names(text, PROP_TAG_RE)
    if not prop_names:
        prompt_props = prompt.get("props") if isinstance(prompt.get("props"), list) else []
        for candidate in prompt_props:
            name = _clean_name(candidate.get("name")) if isinstance(candidate, dict) else ""
            if name and _plain_text_contains_name(text, name):
                prop_names.append(name)
    for name in _dedupe_keep_order(prop_names):
        prompt_candidate = next(
            (item for item in (prompt.get("props") or []) if isinstance(item, dict) and _clean_name(item.get("name")) == name),
            {"name": name},
        )
        asset = _asset_by_id_or_name(props, prompt_candidate)
        _add_reference_item(items, "道具", name, _reference_url(asset or prompt_candidate))

    loc = location or prompt.get("location") or {}
    if not loc and isinstance(prompt.get("source"), dict):
        loc = {
            "id": prompt["source"].get("location_db_id") or prompt["source"].get("location_id"),
            "name": prompt["source"].get("location_name"),
        }
    loc_name = _clean_name(loc.get("name")) if isinstance(loc, dict) else ""
    _add_reference_item(items, "场景", loc_name, _reference_url(loc if isinstance(loc, dict) else {}))

    return items


def build_reference_legend(items: List[Dict[str, str]], start_index: int = 1) -> str:
    if not items:
        return ""
    parts = [
        f"图{index}是{item['type']}：{item['name']}"
        for index, item in enumerate(items, start=start_index)
    ]
    return "参考图说明：" + "。".join(parts) + "。"


def append_reference_legend(prompt: str, items: List[Dict[str, str]], start_index: int = 1) -> str:
    legend = build_reference_legend(items, start_index=start_index)
    if not legend:
        return prompt
    return f"{prompt.rstrip()}\n\n{legend}"


def reference_urls(items: List[Dict[str, str]]) -> List[str]:
    return [item["url"] for item in items if item.get("url")]
