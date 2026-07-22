"""
Storyboard reference image matching helpers.

Keep this module pure: API routes can call it from async handlers without DB work,
and tests can validate prompt/reference behavior without booting the server.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


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


def _reference_image_variants(asset: Dict[str, Any]) -> List[Dict[str, str]]:
    asset = asset or {}
    variants: List[Dict[str, str]] = []
    primary = ""
    for key in ("selected_reference_image", "reference_image", "image_url", "avatar", "pic", "url", "file_url", "path"):
        if asset.get(key):
            primary = asset[key]
            break
    if primary:
        variants.append({
            "url": str(primary),
            "label": "默认",
            "source": "reference_image",
            "angle": "",
        })
    refs = asset.get("reference_images")
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except Exception:
            refs = []
    if isinstance(refs, list):
        for index, item in enumerate(refs, start=1):
            if isinstance(item, str):
                url = item
                label = f"参考图{index}"
                angle = ""
            elif isinstance(item, dict):
                url = (
                    item.get("url")
                    or item.get("file_url")
                    or item.get("image_url")
                    or item.get("reference_image")
                    or item.get("path")
                    or ""
                )
                label = item.get("label") or item.get("name") or item.get("title") or item.get("caption") or item.get("angle") or item.get("view") or f"参考图{index}"
                angle = item.get("angle") or item.get("view") or ""
            else:
                continue
            if url and not any(variant["url"] == str(url) for variant in variants):
                variants.append({
                    "url": str(url),
                    "label": str(label or ""),
                    "source": "reference_images",
                    "angle": str(angle or ""),
                })
    return variants


def _selection_key(asset: Dict[str, Any]) -> str:
    asset_id = asset.get("id") or asset.get("db_id") or asset.get("character_db_id") or asset.get("location_db_id")
    if asset_id not in (None, ""):
        return str(asset_id)
    name = _clean_name(asset.get("name")).replace(" ", "")
    return f"name:{name}" if name else ""


def _selected_variant(asset: Dict[str, Any], selection: Optional[Dict[str, Any]]) -> Tuple[str, str, str]:
    variants = _reference_image_variants(asset)
    fallback = variants[0] if variants else {"url": "", "label": "", "source": ""}
    selected_url = str((selection or {}).get("url") or "")
    if selected_url:
        for variant in variants:
            if variant["url"] == selected_url:
                return variant["url"], variant.get("label") or str((selection or {}).get("label") or ""), variant.get("source") or ""
    return fallback.get("url", ""), fallback.get("label", ""), fallback.get("source", "")


def _reference_selections(prompt_json: Dict[str, Any]) -> Dict[str, Any]:
    selections = prompt_json.get("reference_selections")
    return selections if isinstance(selections, dict) else {}


def select_reference_variant_for_asset(
    prompt_json: Any,
    asset: Dict[str, Any],
    asset_type: str,
) -> Dict[str, str]:
    """Safely resolve a scene-level reference-image selection for one asset.

    The selected URL is accepted only when it still belongs to the asset's
    `reference_image` or `reference_images`; otherwise the asset's primary
    reference image is returned.
    """
    asset = asset or {}
    prompt = _as_dict(prompt_json)
    selections = _reference_selections(prompt)
    selection: Optional[Dict[str, Any]] = None
    if asset_type == "character":
        character_selections = selections.get("characters") if isinstance(selections.get("characters"), dict) else {}
        selection = character_selections.get(_selection_key(asset))
        if selection is None:
            name_key = f"name:{_clean_name(asset.get('name')).replace(' ', '')}"
            selection = character_selections.get(name_key)
    elif asset_type == "location":
        raw_location = selections.get("location")
        selection = raw_location if isinstance(raw_location, dict) else None
    url, label, source = _selected_variant(asset or {}, selection)
    return {
        "url": url,
        "label": label,
        "source": source,
    }


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


def _add_reference_item(
    items: List[Dict[str, str]],
    asset_type: str,
    name: str,
    url: str,
    *,
    variant_label: str = "",
    variant_source: str = "",
) -> None:
    if not name or not url:
        return
    if any(item["url"] == url or (item["type"] == asset_type and item["name"] == name) for item in items):
        return
    item = {"type": asset_type, "name": name, "url": url}
    if variant_label and variant_label != "默认":
        item["variant_label"] = variant_label
    if variant_source:
        item["variant_source"] = variant_source
    items.append(item)


def extract_storyboard_reference_names(
    prompt_json: Any,
    video_prompt: str = "",
) -> Dict[str, List[str]]:
    """Extract ordered role/prop names explicitly referenced by a shot prompt."""
    prompt = _as_dict(prompt_json)
    text = _prompt_text(prompt, video_prompt)
    character_names = _extract_tagged_names(text, ROLE_TAG_RE)
    prop_names = _extract_tagged_names(text, PROP_TAG_RE)
    if not prop_names:
        prompt_props = prompt.get("props") if isinstance(prompt.get("props"), list) else []
        for candidate in prompt_props:
            name = _clean_name(candidate.get("name")) if isinstance(candidate, dict) else ""
            if name and _plain_text_contains_name(text, name):
                prop_names.append(name)
    return {
        "characters": character_names,
        "props": _dedupe_keep_order(prop_names),
    }


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
    items: List[Dict[str, str]] = []
    characters = characters or []
    props = props or []

    referenced_names = extract_storyboard_reference_names(prompt, video_prompt)
    for name in referenced_names["characters"]:
        asset = _asset_by_name(characters, name)
        if asset:
            selected = select_reference_variant_for_asset(prompt, asset, "character")
            url, variant_label, variant_source = selected["url"], selected["label"], selected["source"]
        else:
            url, variant_label, variant_source = _reference_url({}), "", ""
        _add_reference_item(
            items,
            "角色",
            name,
            url,
            variant_label=variant_label,
            variant_source=variant_source,
        )

    for name in referenced_names["props"]:
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
    if isinstance(loc, dict):
        selected = select_reference_variant_for_asset(prompt, loc, "location")
        url, variant_label, variant_source = selected["url"], selected["label"], selected["source"]
    else:
        url, variant_label, variant_source = "", "", ""
    _add_reference_item(
        items,
        "场景",
        loc_name,
        url,
        variant_label=variant_label,
        variant_source=variant_source,
    )

    return items


def build_reference_legend(items: List[Dict[str, str]], start_index: int = 1) -> str:
    if not items:
        return ""
    parts = []
    for index, item in enumerate(items, start=start_index):
        item_type = item.get("type") or "参考图"
        name = _clean_name(item.get("name"))
        variant_label = _clean_name(item.get("variant_label"))
        suffix = f"，{variant_label}" if variant_label else ""
        parts.append(f"图{index}是{item_type}：{name}{suffix}" if name else f"图{index}是{item_type}{suffix}")
    return "参考图说明：" + "。".join(parts) + "。"


def append_reference_legend(prompt: str, items: List[Dict[str, str]], start_index: int = 1) -> str:
    legend = build_reference_legend(items, start_index=start_index)
    if not legend:
        return prompt
    return f"{prompt.rstrip()}\n\n{legend}"


def append_storyboard_visual_suffix(
    prompt: str,
    *,
    style: Any = "",
    composition_preference: Any = "",
) -> str:
    """Append authoritative storyboard visual settings to the prompt tail.

    Existing identical suffix lines are moved to the tail instead of duplicated.
    This keeps the helper safe to call both before and after optional LLM rewriting.
    """
    suffix_lines = []
    style_text = _clean_name(style)
    composition_text = _clean_name(composition_preference)
    if style_text:
        suffix_lines.append(f"图片风格：{style_text}")
    if composition_text:
        suffix_lines.append(f"构图倾向：{composition_text}")
    if not suffix_lines:
        return str(prompt or "").rstrip()

    suffix_set = set(suffix_lines)
    body_lines = [
        line
        for line in str(prompt or "").rstrip().splitlines()
        if line.strip() not in suffix_set
    ]
    body = "\n".join(body_lines).rstrip()
    suffix = "\n".join(suffix_lines)
    return f"{body}\n\n{suffix}" if body else suffix


def reference_urls(items: List[Dict[str, str]]) -> List[str]:
    return [item["url"] for item in items if item.get("url")]
