"""MiniMax H3 I2VA/FL2VA 提示词优化的纯函数（无数据库依赖）。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from config.constant import (
    H3_PROMPT_OPTIMIZE_VARIANT_FL2VA,
    H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
)

_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "minimax_h3_i2va_fl2va_base_en.txt"
_I2VA_INSTRUCTION = (
    "下面是原本视频的提示词，已知有一张输入图片作为首帧图，"
    "请你修改为符合以上规范的提示词"
)
_FL2VA_INSTRUCTION = (
    "下面是原本视频的提示词，已知有两张输入图片分别作为首帧图和尾帧图，"
    "目标视频时长为 {duration:.2f} 秒，请你修改为符合以上规范的提示词"
)
_FENCE_RE = re.compile(r"^```(?:\w+)?\s*|\s*```$", re.MULTILINE)


def parse_extra_config(ai_tool: Any) -> Dict[str, Any]:
    raw = getattr(ai_tool, "extra_config", None)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def split_media_paths(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def resolve_h3_prompt_variant(ai_tool: Any) -> Optional[str]:
    """仅首帧 → I2VA；有尾帧 → FL2VA；无首帧 → None。"""
    image_urls = split_media_paths(getattr(ai_tool, "image_path", None))
    first = image_urls[0] if image_urls else None
    last = image_urls[1] if len(image_urls) > 1 else None
    if not first:
        refs = split_media_paths(getattr(ai_tool, "reference_images", None))
        if refs:
            first = refs[0]
            last = refs[1] if len(refs) > 1 else None
    extra = parse_extra_config(ai_tool)
    if not last and extra.get("image_mode") == "first_last_with_ref":
        refs = split_media_paths(getattr(ai_tool, "reference_images", None))
        if refs:
            last = refs[0]
    if not first:
        return None
    if last:
        return H3_PROMPT_OPTIMIZE_VARIANT_FL2VA
    return H3_PROMPT_OPTIMIZE_VARIANT_I2VA


def load_h3_prompt_template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def build_h3_optimize_user_message(
    original_prompt: str,
    variant: str,
    duration: float,
    template: Optional[str] = None,
) -> str:
    guide = template if template is not None else load_h3_prompt_template()
    if variant == H3_PROMPT_OPTIMIZE_VARIANT_FL2VA:
        instruction = _FL2VA_INSTRUCTION.format(duration=float(duration or 5))
    else:
        instruction = _I2VA_INSTRUCTION
    body = (original_prompt or "").strip() or "(empty original prompt)"
    return f"{guide.rstrip()}\n\n{instruction}\n\n{body}\n"


def strip_prompt_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_RE.sub("", cleaned).strip()
    return cleaned


def validate_h3_optimized_prompt(text: str, variant: str) -> bool:
    prompt = strip_prompt_fences(text)
    if not prompt:
        return False
    lowered = prompt.lower()
    has_fields = (
        "integrated_multimodal_description:" in lowered
        and "overall_soundscape:" in lowered
        and "non_diegetic_music:" in lowered
    )
    if not has_fields:
        return False
    if variant == H3_PROMPT_OPTIMIZE_VARIANT_FL2VA:
        return "how the reference pictures align" in lowered
    return "at 0.00 seconds" in lowered and "<picture 1>" in lowered


def merge_h3_prompt_extra_config(
    extra_config: Any,
    *,
    original_prompt: str,
    optimized_prompt: str,
    variant: str,
    fallback: bool,
) -> str:
    data = extra_config if isinstance(extra_config, dict) else {}
    if not data and extra_config:
        try:
            parsed = json.loads(extra_config) if isinstance(extra_config, str) else extra_config
            if isinstance(parsed, dict):
                data = dict(parsed)
        except (json.JSONDecodeError, TypeError):
            data = {}
    else:
        data = dict(data)
    if not data.get("original_prompt"):
        data["original_prompt"] = original_prompt
    data["h3_prompt_optimize"] = {
        "variant": variant,
        "original_prompt": original_prompt,
        "optimized_prompt": optimized_prompt,
        "fallback": bool(fallback),
    }
    return json.dumps(data, ensure_ascii=False)


def parse_storyboard_dialogue_model(config_json: Any) -> Optional[tuple]:
    """从 storyboard.config_json 解析用户配置的对话模型（selectedLlmModel）。

    config_json 可为 JSON 字符串、dict 或 None。selectedLlmModel 可为
    {model, model_id, vendor_id} 对象或模型名字符串（前端 resolveLlmModelSelection 产物）。

    纯解析，无数据库依赖。返回 (model, vendor_id) 或 None；vendor_id 为 None 表示按模型名路由。
    """
    if not config_json:
        return None
    data = config_json
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(data, dict):
        return None
    selection = data.get("selectedLlmModel")
    if not selection:
        return None
    if isinstance(selection, str):
        model = selection.strip()
        return (model, None) if model else None
    if isinstance(selection, dict):
        model = str(selection.get("model") or selection.get("name") or "").strip()
        if not model:
            return None
        raw_vendor_id = selection.get("vendor_id")
        try:
            vendor_id = int(raw_vendor_id) if raw_vendor_id not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            vendor_id = None
        return (model, vendor_id)
    return None
