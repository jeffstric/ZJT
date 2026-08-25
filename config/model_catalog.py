#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""场景模型目录：性价比 / 效果双档 + 供应商折叠。

推荐只影响列表展示和首次默认，不覆盖用户已保存偏好或任务快照。
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

TRACK_VALUE = "value"
TRACK_QUALITY = "quality"
TRACK_CUSTOM = "custom"

VALID_TRACKS = (TRACK_VALUE, TRACK_QUALITY, TRACK_CUSTOM)


class ModelScene:
    """场景键，与 media_pref / TaskCategory 对齐。"""
    LLM_CHAT = "llm.chat"
    LLM_SCRIPT_SPLIT = "llm.script_split"
    LLM_MARKETING = "llm.marketing"
    LLM_STYLE_RECOGNIZE = "llm.style_recognize"
    LLM_AGENT = "llm.agent"
    IMAGE_TEXT_TO_IMAGE = "image.text_to_image"
    IMAGE_IMAGE_EDIT = "image.image_edit"
    IMAGE_GRID = "image.grid"
    IMAGE_SCRIPT_WRITER = "image.script_writer"
    VIDEO_TEXT_TO_VIDEO = "video.text_to_video"
    VIDEO_IMAGE_TO_VIDEO = "video.image_to_video"
    VIDEO_REFERENCE_TO_VIDEO = "video.reference_to_video"
    VIDEO_DIGITAL_HUMAN = "video.digital_human"


@dataclass(frozen=True)
class RecoSlot:
    canonical: str
    preferred_vendors: Tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class SceneReco:
    scene: str
    value: RecoSlot
    quality: RecoSlot


_DEEPSEEK_VENDORS = ("deepseek", "zjt_api")
_DOUBAO_VENDORS = ("volcengine", "zjt_api")

_FLASH = RecoSlot(
    canonical="deepseek-v4-flash",
    preferred_vendors=_DEEPSEEK_VENDORS,
    reason="更快更便宜，适合日常对话和草稿",
)
_PRO = RecoSlot(
    canonical="deepseek-v4-pro",
    preferred_vendors=_DEEPSEEK_VENDORS,
    reason="理解力和稳定性更好，适合正式成片",
)
_DOUBAO_LITE = RecoSlot(
    canonical="doubao-seed-2-0-lite",
    preferred_vendors=_DOUBAO_VENDORS,
    reason="更快更便宜，适合营销日常对话",
)
_DOUBAO_PRO = RecoSlot(
    canonical="doubao-seed-2-0-pro",
    preferred_vendors=_DOUBAO_VENDORS,
    reason="效果更好，适合需要更高质量的营销对话",
)

SCENE_RECOS: Dict[str, SceneReco] = {
    ModelScene.LLM_CHAT: SceneReco(ModelScene.LLM_CHAT, _FLASH, _PRO),
    ModelScene.LLM_SCRIPT_SPLIT: SceneReco(
        ModelScene.LLM_SCRIPT_SPLIT,
        RecoSlot("deepseek-v4-flash", _DEEPSEEK_VENDORS, "更快更便宜，适合日常拆分和草稿"),
        RecoSlot("deepseek-v4-pro", _DEEPSEEK_VENDORS, "理解力和稳定性更好，适合正式成片拆分"),
    ),
    ModelScene.LLM_MARKETING: SceneReco(ModelScene.LLM_MARKETING, _DOUBAO_LITE, _DOUBAO_PRO),
    ModelScene.LLM_STYLE_RECOGNIZE: SceneReco(
        ModelScene.LLM_STYLE_RECOGNIZE, _DOUBAO_LITE, _DOUBAO_PRO,
    ),
    ModelScene.LLM_AGENT: SceneReco(ModelScene.LLM_AGENT, _FLASH, _PRO),
    ModelScene.IMAGE_TEXT_TO_IMAGE: SceneReco(
        ModelScene.IMAGE_TEXT_TO_IMAGE,
        RecoSlot("gpt-image-2", reason="文生图性价比与效果均推荐 GPT Image 2"),
        RecoSlot("gpt-image-2", reason="文生图性价比与效果均推荐 GPT Image 2"),
    ),
    ModelScene.IMAGE_IMAGE_EDIT: SceneReco(
        ModelScene.IMAGE_IMAGE_EDIT,
        RecoSlot("gpt-image-2", reason="改图性价比与效果均推荐 GPT Image 2"),
        RecoSlot("gpt-image-2", reason="改图性价比与效果均推荐 GPT Image 2"),
    ),
    ModelScene.IMAGE_GRID: SceneReco(
        ModelScene.IMAGE_GRID,
        RecoSlot("gpt-image-2", reason="宫格生图推荐 GPT Image 2"),
        RecoSlot("gpt-image-2", reason="宫格生图推荐 GPT Image 2"),
    ),
    ModelScene.IMAGE_SCRIPT_WRITER: SceneReco(
        ModelScene.IMAGE_SCRIPT_WRITER,
        RecoSlot("gpt-image-2", reason="剧本生图更快更便宜"),
        RecoSlot("seedream-5.0-pro", reason="剧本生图画质更好（Seedream 5.0 Pro）"),
    ),
    ModelScene.VIDEO_TEXT_TO_VIDEO: SceneReco(
        ModelScene.VIDEO_TEXT_TO_VIDEO,
        RecoSlot("minimax_h3", reason="文生视频更快更便宜"),
        RecoSlot("seedance_2_0", reason="画质和运动更稳，适合正式成片"),
    ),
    ModelScene.VIDEO_IMAGE_TO_VIDEO: SceneReco(
        ModelScene.VIDEO_IMAGE_TO_VIDEO,
        RecoSlot("minimax_h3", reason="图生视频更快更便宜"),
        RecoSlot("seedance_2_0", reason="画质和运动更稳，适合正式成片"),
    ),
    ModelScene.VIDEO_REFERENCE_TO_VIDEO: SceneReco(
        ModelScene.VIDEO_REFERENCE_TO_VIDEO,
        RecoSlot("minimax_h3_r2v", reason="参考生视频更快更便宜（MiniMax H3）"),
        RecoSlot("seedance_2_0", reason="参考生视频画质和运动更稳（Seedance 2.0）"),
    ),
    ModelScene.VIDEO_DIGITAL_HUMAN: SceneReco(
        ModelScene.VIDEO_DIGITAL_HUMAN,
        RecoSlot("digital_human_ltx2_3_voice", reason="数字人性价比高"),
        RecoSlot("digital_human_minimax_h3", reason="数字人效果更好"),
    ),
}

# short_key / model_name -> 系列名（全部模型分组用）
MODEL_FAMILIES: Dict[str, str] = {
    "deepseek-v4-flash": "DeepSeek",
    "deepseek-v4-pro": "DeepSeek",
    "doubao-seed-2-0-lite": "Doubao",
    "doubao-seed-2-0-pro": "Doubao",
    "qwen3.5-plus": "Qwen",
    "qwen3.6-plus": "Qwen",
    "qwen-image-edit": "Qwen",
    "gemini-2.5-flash": "nano-banana",
    "gemini-3-pro": "nano-banana",
    "gemini-3.1-flash": "nano-banana",
    "seedream-5.0": "Seedream",
    "seedream-4.5": "Seedream",
    "seedream-5.0-pro": "Seedream",
    "gpt-image-2": "GPT Image",
    "seedance_2_0": "Seedance",
    "seedance_2_0_fast": "Seedance",
    "seedance_2_0_mini": "Seedance",
    "seedance_2_5": "Seedance",
    "seedance_1_5_pro": "Seedance",
    "happy_horse": "Happy Horse",
    "happy_horse_r2v": "Happy Horse",
    "happy_horse_t2v": "Happy Horse",
    "ltx2": "LTX",
    "ltx2_3": "LTX",
    "minimax_h3": "MiniMax",
    "minimax_h3_r2v": "MiniMax",
    "digital_human_minimax_h3": "MiniMax",
    "vidu": "Vidu",
    "vidu_q2": "Vidu",
    "digital_human": "数字人",
    "digital_human_ltx2_3_voice": "数字人",
}

SCENE_ALIASES = {
    "chat": ModelScene.LLM_CHAT,
    "dialogue": ModelScene.LLM_CHAT,
    "script_split": ModelScene.LLM_SCRIPT_SPLIT,
    "split": ModelScene.LLM_SCRIPT_SPLIT,
    "marketing": ModelScene.LLM_MARKETING,
    "style": ModelScene.LLM_STYLE_RECOGNIZE,
    "style_recognize": ModelScene.LLM_STYLE_RECOGNIZE,
    "text_to_image": ModelScene.IMAGE_TEXT_TO_IMAGE,
    "image_edit": ModelScene.IMAGE_IMAGE_EDIT,
    "grid": ModelScene.IMAGE_GRID,
    "script_writer": ModelScene.IMAGE_SCRIPT_WRITER,
    "text_to_video": ModelScene.VIDEO_TEXT_TO_VIDEO,
    "image_to_video": ModelScene.VIDEO_IMAGE_TO_VIDEO,
    "reference_to_video": ModelScene.VIDEO_REFERENCE_TO_VIDEO,
    "digital_human": ModelScene.VIDEO_DIGITAL_HUMAN,
}


def normalize_scene(scene: Optional[str]) -> Optional[str]:
    if not scene:
        return None
    key = str(scene).strip().lower()
    if key in SCENE_RECOS:
        return key
    return SCENE_ALIASES.get(key)


def normalize_track(track: Optional[str], default: str = TRACK_VALUE) -> str:
    value = (track or default or TRACK_VALUE).strip().lower()
    if value in ("cheap", "fast", "性价比"):
        return TRACK_VALUE
    if value in ("effect", "quality", "效果"):
        return TRACK_QUALITY
    if value in VALID_TRACKS:
        return value
    return default


def get_scene_reco(scene: Optional[str]) -> Optional[SceneReco]:
    key = normalize_scene(scene)
    if not key:
        return None
    return SCENE_RECOS.get(key)


def get_model_family(canonical: Optional[str]) -> str:
    if not canonical:
        return "其它"
    key = str(canonical).strip()
    if key in MODEL_FAMILIES:
        return MODEL_FAMILIES[key]
    lowered = key.lower()
    for name, family in MODEL_FAMILIES.items():
        if name.lower() == lowered:
            return family
    if "deepseek" in lowered:
        return "DeepSeek"
    if "doubao" in lowered or "seed-2-0" in lowered:
        return "Doubao"
    if "qwen" in lowered:
        return "Qwen"
    if "seedance" in lowered:
        return "Seedance"
    if "seedream" in lowered:
        return "Seedream"
    if "nano-banana" in lowered or "gemini" in lowered:
        return "nano-banana"
    if "happy_horse" in lowered or "happy horse" in lowered:
        return "Happy Horse"
    return "其它"


def llm_canonical(model: Dict[str, Any]) -> str:
    return str(model.get("name") or model.get("model") or model.get("model_name") or "").strip()


def task_canonical(task: Dict[str, Any]) -> str:
    return str(task.get("short_key") or task.get("key") or task.get("canonical") or "").strip()


def match_canonical(item: str, target: str) -> bool:
    if not item or not target:
        return False
    left = item.strip().lower()
    right = target.strip().lower()
    if left == right:
        return True
    # 允许「deepseek-v4-flash（性价比）」这类标签，但不让 seedance_2_0 命中 seedance_2_0_fast
    if left.startswith(right):
        nxt = left[len(right):len(right) + 1]
        return nxt in {"", " ", "（", "(", "·", "/", "|"}
    return False


def _vendor_of(model: Dict[str, Any]) -> str:
    return str(model.get("vendor_name") or "").strip().lower()


def pick_llm_route(
    candidates: Sequence[Dict[str, Any]],
    preferred_vendors: Sequence[str] = (),
) -> Optional[Dict[str, Any]]:
    """同一规范模型下选默认供应商。"""
    usable = [m for m in candidates if m]
    if not usable:
        return None
    for vendor in preferred_vendors:
        hit = next((m for m in usable if _vendor_of(m) == str(vendor).lower()), None)
        if hit:
            return hit
    with_threshold = [
        m for m in usable
        if m.get("input_token_threshold") not in (None, "", 0)
    ]
    if with_threshold:
        return max(with_threshold, key=lambda m: float(m.get("input_token_threshold") or 0))
    return usable[0]


def _find_llm(available: Sequence[Dict[str, Any]], slot: RecoSlot) -> Optional[Dict[str, Any]]:
    matches = [m for m in available if match_canonical(llm_canonical(m), slot.canonical)]
    return pick_llm_route(matches, slot.preferred_vendors)


def _find_task(available: Sequence[Dict[str, Any]], slot: RecoSlot) -> Optional[Dict[str, Any]]:
    for item in available:
        if match_canonical(task_canonical(item), slot.canonical):
            return item
        name = str(item.get("name") or "")
        if match_canonical(name, slot.canonical):
            return item
    return None


def resolve_track_item(
    scene: Optional[str],
    available: Sequence[Dict[str, Any]],
    track: str = TRACK_VALUE,
    kind: str = "llm",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """返回 (命中项, 实际档位)。指定档不可用时落到另一档。"""
    reco = get_scene_reco(scene)
    if not reco or not available:
        return None, None
    wanted = normalize_track(track)
    if wanted == TRACK_CUSTOM:
        return None, TRACK_CUSTOM
    primary = reco.value if wanted == TRACK_VALUE else reco.quality
    secondary = reco.quality if wanted == TRACK_VALUE else reco.value
    finder = _find_llm if kind == "llm" else _find_task
    hit = finder(available, primary)
    if hit:
        return hit, wanted
    hit = finder(available, secondary)
    if hit:
        return hit, TRACK_QUALITY if wanted == TRACK_VALUE else TRACK_VALUE
    return None, None


def _track_of_canonical(reco: SceneReco, canonical: str) -> Optional[str]:
    if match_canonical(canonical, reco.value.canonical):
        return TRACK_VALUE
    if match_canonical(canonical, reco.quality.canonical):
        return TRACK_QUALITY
    return None


def annotate_llm_models(
    models: Sequence[Dict[str, Any]],
    scene: Optional[str] = None,
) -> List[Dict[str, Any]]:
    reco = get_scene_reco(scene)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for model in models:
        key = llm_canonical(model).lower()
        groups.setdefault(key, []).append(model)

    annotated: List[Dict[str, Any]] = []
    for model in models:
        item = dict(model)
        name = llm_canonical(model)
        track = _track_of_canonical(reco, name) if reco else None
        preferred = ()
        reason = ""
        if reco and track == TRACK_VALUE:
            preferred = reco.value.preferred_vendors
            reason = reco.value.reason
        elif reco and track == TRACK_QUALITY:
            preferred = reco.quality.preferred_vendors
            reason = reco.quality.reason
        default_route = pick_llm_route(groups.get(name.lower(), []), preferred)
        item["canonical"] = name
        item["family"] = get_model_family(name)
        item["track"] = track
        item["reason"] = reason
        item["is_default_route"] = bool(
            default_route is not None
            and str(default_route.get("vendor_id") or "") == str(model.get("vendor_id") or "")
            and str(default_route.get("model_id") or default_route.get("id") or "")
            == str(model.get("model_id") or model.get("id") or "")
        )
        annotated.append(item)
    return annotated


def annotate_task_models(
    tasks: Sequence[Dict[str, Any]],
    scene: Optional[str] = None,
) -> List[Dict[str, Any]]:
    reco = get_scene_reco(scene)
    annotated: List[Dict[str, Any]] = []
    for task in tasks:
        item = dict(task)
        canonical = task_canonical(task)
        track = _track_of_canonical(reco, canonical) if reco else None
        item["canonical"] = canonical
        item["family"] = get_model_family(canonical)
        item["track"] = track
        if reco and track == TRACK_VALUE:
            item["reason"] = reco.value.reason
        elif reco and track == TRACK_QUALITY:
            item["reason"] = reco.quality.reason
        else:
            item["reason"] = ""
        annotated.append(item)
    return annotated


def _route_payload(item: Optional[Dict[str, Any]], kind: str) -> Optional[Dict[str, Any]]:
    if not item:
        return None
    if kind == "llm":
        return {
            "model_id": item.get("model_id") if item.get("model_id") is not None else item.get("id"),
            "vendor_id": item.get("vendor_id"),
            "vendor_name": item.get("vendor_name"),
            "name": llm_canonical(item),
        }
    return {
        "task_id": item.get("task_id") if item.get("task_id") is not None else item.get("id"),
        "short_key": task_canonical(item),
        "name": item.get("name") or task_canonical(item),
        "key": item.get("key"),
    }


def build_tracks_payload(
    scene: Optional[str],
    available: Sequence[Dict[str, Any]],
    kind: str = "llm",
) -> Dict[str, Any]:
    reco = get_scene_reco(scene)
    if not reco:
        return {}
    finder = _find_llm if kind == "llm" else _find_task
    tracks = {}
    for track, slot in ((TRACK_VALUE, reco.value), (TRACK_QUALITY, reco.quality)):
        hit = finder(available, slot)
        tracks[track] = {
            "canonical": slot.canonical,
            "reason": slot.reason,
            "available": hit is not None,
            "default_route": _route_payload(hit, kind),
        }
    return {
        "scene": reco.scene,
        "tracks": tracks,
        "default_track": TRACK_VALUE,
    }


def tracks_message(catalog: Dict[str, Any]) -> str:
    if not catalog or not catalog.get("tracks"):
        return ""
    tracks = catalog["tracks"]
    value = tracks.get(TRACK_VALUE) or {}
    quality = tracks.get(TRACK_QUALITY) or {}
    value_name = value.get("canonical") or "—"
    quality_name = quality.get("canonical") or "—"
    return (
        f"本场景性价比用 {value_name}，效果用 {quality_name}；"
        "未指定时用性价比。不要在未列出的模型里猜测。"
    )


def scene_catalog_map() -> Dict[str, Dict[str, Any]]:
    """给前端的静态目录（不含可用性）。"""
    result = {}
    for scene, reco in SCENE_RECOS.items():
        result[scene] = {
            "scene": scene,
            "default_track": TRACK_VALUE,
            "tracks": {
                TRACK_VALUE: {
                    "canonical": reco.value.canonical,
                    "reason": reco.value.reason,
                    "preferred_vendors": list(reco.value.preferred_vendors),
                },
                TRACK_QUALITY: {
                    "canonical": reco.quality.canonical,
                    "reason": reco.quality.reason,
                    "preferred_vendors": list(reco.quality.preferred_vendors),
                },
            },
        }
    return result


def infer_track_from_item(
    scene: Optional[str],
    item: Optional[Dict[str, Any]],
    kind: str = "llm",
) -> str:
    if not item:
        return TRACK_CUSTOM
    reco = get_scene_reco(scene)
    if not reco:
        return TRACK_CUSTOM
    canonical = llm_canonical(item) if kind == "llm" else task_canonical(item)
    return _track_of_canonical(reco, canonical) or TRACK_CUSTOM
