"""MiniMax H3 I2VA/FL2VA/Ref2VA 提示词优化的纯函数（无数据库依赖）。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from config.constant import (
    H3_PROMPT_OPTIMIZE_VARIANT_FL2VA,
    H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
    H3_PROMPT_OPTIMIZE_VARIANT_REF2VA,
)
from config.unified_config import DriverKey

_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "minimax_h3_i2va_fl2va_base_en.txt"
_REF2VA_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "minimax_h3_ref2va_ref_en.txt"
_I2VA_INSTRUCTION = (
    "下面是原本视频的提示词，已知有一张输入图片作为首帧图，"
    "请你修改为符合以上规范的提示词"
)
_FL2VA_INSTRUCTION = (
    "下面是原本视频的提示词，已知有两张输入图片分别作为首帧图和尾帧图，"
    "目标视频时长为 {duration:.2f} 秒，请你修改为符合以上规范的提示词"
)
_FENCE_RE = re.compile(r"^```(?:\w+)?\s*|\s*```$", re.MULTILINE)
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
# 书名号《》不参与：书名不是对话；英文直引号/中文弯引号/日式引号均为台词常见形态。
_QUOTED_SPAN_RE = re.compile(r"[\"“「『]([^\"”」』]+)[\"”」』]")


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


def resolve_h3_reference_asset_counts(ai_tool: Any) -> Dict[str, int]:
    """统计参考生视频的参考资产数量（参考图/参考视频/参考音频）。"""
    return {
        "images": len(split_media_paths(getattr(ai_tool, "reference_images", None))),
        "videos": len(split_media_paths(getattr(ai_tool, "video_path", None))),
        "audios": len(split_media_paths(getattr(ai_tool, "audio_path", None))),
    }


def resolve_h3_prompt_variant(ai_tool: Any, task_key: Optional[str] = None) -> Optional[str]:
    """参考生视频（多参考资产）→ Ref2VA；仅首帧 → I2VA；有尾帧 → FL2VA；无可用输入 → None。"""
    if task_key == DriverKey.MINIMAX_H3_REFERENCE_TO_VIDEO:
        counts = resolve_h3_reference_asset_counts(ai_tool)
        if counts["images"] or counts["videos"] or counts["audios"]:
            return H3_PROMPT_OPTIMIZE_VARIANT_REF2VA
        return None
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


def load_h3_prompt_template(variant: Optional[str] = None) -> str:
    path = _REF2VA_TEMPLATE_PATH if variant == H3_PROMPT_OPTIMIZE_VARIANT_REF2VA else _TEMPLATE_PATH
    return path.read_text(encoding="utf-8")


def _build_ref2va_instruction(ref_counts: Optional[Dict[str, int]], duration: float) -> str:
    counts = ref_counts or {}
    images = int(counts.get("images") or 0)
    videos = int(counts.get("videos") or 0)
    audios = int(counts.get("audios") or 0)
    assets = []
    if images:
        assets.append(f"{images} 张输入参考图片（按顺序对应 <picture_1>~<picture_{images}>）")
    if videos:
        assets.append(f"{videos} 个输入参考视频（按顺序对应 <video_1>~<video_{videos}>）")
    if audios:
        assets.append(f"{audios} 个输入参考音频（按顺序对应 <audio_1>~<audio_{audios}>）")
    asset_text = "、".join(assets) if assets else "若干输入参考资产"
    return (
        f"下面是原本视频的提示词，已知有{asset_text}，"
        f"目标视频时长为 {float(duration or 5):.2f} 秒，请你修改为符合以上规范的提示词；"
        "参考标签与输入资产按顺序一一对应"
    )


def _extract_quoted_cjk_spans(text: str) -> list:
    """提取引号包裹且含 CJK 字符(中日韩)的片段。

    引号是台词/歌词/画面文字的常见形态信号,但强调、术语等描述性用法也会用引号,
    因此仅用于生成提示信息,语义由 LLM 自行判断(见 _build_dialogue_fidelity_note)。
    """
    spans = []
    for match in _QUOTED_SPAN_RE.finditer(text or ""):
        span = match.group(1)
        if _CJK_RE.search(span):
            spans.append(span)
    return spans


def _detect_cjk_language(spans: list) -> str:
    """按片段字符集判断语言标签建议:谚文→Korean,假名→Japanese,否则 Chinese。"""
    text = "".join(spans)
    if _HANGUL_RE.search(text):
        return "Korean"
    if _KANA_RE.search(text):
        return "Japanese"
    return "Chinese"


def _build_dialogue_fidelity_note(quoted_spans: list) -> str:
    """构造条件式对话保真提示:点名列出引号 CJK 片段,角色判断(台词还是描述)交给 LLM。"""
    language = _detect_cjk_language(quoted_spans)
    listed = "\n".join(f'- "{span}"' for span in quoted_spans)
    return (
        f"原始提示词中存在以下引号包裹的 {language} 片段:\n{listed}\n"
        f"若它们是角色说出的台词、唱出的歌词或画面中的可见文字,"
        f"必须逐字保留在 <d> 内(语言标签写 [{language}]),严禁翻译或改写;"
        f"若它们只是动作、氛围、术语等描述性用法,则正常按英文规范转写。"
    )


def build_h3_optimize_user_message(
    original_prompt: str,
    variant: str,
    duration: float,
    template: Optional[str] = None,
    ref_counts: Optional[Dict[str, int]] = None,
) -> str:
    guide = template if template is not None else load_h3_prompt_template(variant)
    if variant == H3_PROMPT_OPTIMIZE_VARIANT_REF2VA:
        instruction = _build_ref2va_instruction(ref_counts, duration)
    elif variant == H3_PROMPT_OPTIMIZE_VARIANT_FL2VA:
        instruction = _FL2VA_INSTRUCTION.format(duration=float(duration or 5))
    else:
        instruction = _I2VA_INSTRUCTION
    quoted_spans = _extract_quoted_cjk_spans(original_prompt)
    if quoted_spans:
        instruction = f"{instruction}\n{_build_dialogue_fidelity_note(quoted_spans)}"
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
    if variant == H3_PROMPT_OPTIMIZE_VARIANT_REF2VA:
        return all(
            field in lowered
            for field in (
                "subject_definitions:",
                "summary:",
                "retention_analysis:",
                "detailed_description:",
                "overall_soundscape:",
                "non_diegetic_music:",
            )
        )
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
