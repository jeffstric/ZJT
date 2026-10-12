"""MiniMax H3 I2VA/FL2VA/Ref2VA/KFRef 提示词优化的纯函数（无数据库依赖）。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.constant import (
    H3_PROMPT_OPTIMIZE_VARIANT_FL2VA,
    H3_PROMPT_OPTIMIZE_VARIANT_I2VA,
    H3_PROMPT_OPTIMIZE_VARIANT_KF_REF,
    H3_PROMPT_OPTIMIZE_VARIANT_REF2VA,
    MAX_VOICE_REFERENCE_AUDIOS,
)
from config.unified_config import DriverKey

_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "minimax_h3_i2va_fl2va_base_en.txt"
_REF2VA_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "minimax_h3_ref2va_ref_en.txt"
_KFREF_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "minimax_h3_kfref_en.txt"
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
# 分镜参考模式提交后写进提示词的槽位说明。1-based，与参考图列表下标对应。
_H3_FIRST_FRAME_MARK_RE = re.compile(r"图(\d+)是首帧")
_H3_LAST_FRAME_MARK_RE = re.compile(r"图(\d+)是尾帧")
_H3_KF_ROLE_START = "start"
_H3_KF_ROLE_END = "end"
_H3_KF_ROLE_REFERENCE = "reference"
_H3_KF_ROLE_EMPTY = "empty"


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


def _marked_frame_index(match: Optional[re.Match], url_count: int) -> Optional[int]:
    """把「图N」换成 0-based 下标。越界视为缺失，不占用列表里的其他图。"""
    if not match:
        return None
    index = int(match.group(1)) - 1
    if 0 <= index < url_count:
        return index
    return None


def _kf_slot(url: str, role: str) -> tuple:
    if url:
        return url, role
    return "", _H3_KF_ROLE_EMPTY


def assign_h3_keyframe_ref_pictures(image_urls: Optional[List[str]], prompt: Optional[str]) -> Dict[str, Any]:
    """按原文「图N是首帧 / 图N是尾帧」把参考图列表填进 Picture 1/2/3。

    Picture 2 只放角色、场景或道具参考，不会是尾帧。
    只点名首帧时，Picture 3 是第二张参考；只点名尾帧时，Picture 3 才是结束关键帧。
    没有标记时，前三张都当参考图。超出槽位的中间参考放进 unused_urls。
    """
    urls = [str(item).strip() for item in (image_urls or []) if str(item or "").strip()]
    text = prompt or ""
    first_match = _H3_FIRST_FRAME_MARK_RE.search(text)
    last_match = _H3_LAST_FRAME_MARK_RE.search(text)
    first_index = _marked_frame_index(first_match, len(urls))
    last_index = _marked_frame_index(last_match, len(urls))
    consumed = {index for index in (first_index, last_index) if index is not None}
    refs = [url for index, url in enumerate(urls) if index not in consumed]

    if first_match and last_match:
        picture_1, role_1 = _kf_slot(urls[first_index] if first_index is not None else "", _H3_KF_ROLE_START)
        if refs:
            picture_2, role_2 = refs[0], _H3_KF_ROLE_REFERENCE
            unused = refs[1:]
        else:
            picture_2, role_2 = "", _H3_KF_ROLE_EMPTY
            unused = []
        picture_3, role_3 = _kf_slot(urls[last_index] if last_index is not None else "", _H3_KF_ROLE_END)
    elif first_match:
        picture_1, role_1 = _kf_slot(urls[first_index] if first_index is not None else "", _H3_KF_ROLE_START)
        picture_2, role_2 = _kf_slot(refs[0] if refs else "", _H3_KF_ROLE_REFERENCE)
        picture_3, role_3 = _kf_slot(refs[1] if len(refs) > 1 else "", _H3_KF_ROLE_REFERENCE)
        unused = refs[2:]
    elif last_match:
        picture_1, role_1 = _kf_slot(refs[0] if refs else "", _H3_KF_ROLE_REFERENCE)
        picture_2, role_2 = _kf_slot(refs[1] if len(refs) > 1 else "", _H3_KF_ROLE_REFERENCE)
        picture_3, role_3 = _kf_slot(urls[last_index] if last_index is not None else "", _H3_KF_ROLE_END)
        unused = refs[2:]
    else:
        slots = []
        for index in range(3):
            if index < len(urls):
                slots.append((urls[index], _H3_KF_ROLE_REFERENCE))
            else:
                slots.append(("", _H3_KF_ROLE_EMPTY))
        (picture_1, role_1), (picture_2, role_2), (picture_3, role_3) = slots
        unused = urls[3:]

    return {
        "picture_1": picture_1,
        "picture_2": picture_2,
        "picture_3": picture_3,
        "roles": {
            "picture_1": role_1,
            "picture_2": role_2,
            "picture_3": role_3,
        },
        "unused_urls": unused,
    }


def h3_slot_source_prompt(extra_config: Any, fallback_prompt: Optional[str] = None) -> str:
    """槽位标记要从优化前的原文读。优化结果会改掉「图N是首帧」。"""
    data: Dict[str, Any] = {}
    if isinstance(extra_config, dict):
        data = extra_config
    elif extra_config:
        try:
            parsed = json.loads(extra_config) if isinstance(extra_config, str) else extra_config
            if isinstance(parsed, dict):
                data = parsed
        except (json.JSONDecodeError, TypeError):
            data = {}
    meta = data.get("h3_prompt_optimize")
    if isinstance(meta, dict) and str(meta.get("original_prompt") or "").strip():
        return str(meta.get("original_prompt"))
    if str(data.get("original_prompt") or "").strip():
        return str(data.get("original_prompt"))
    return fallback_prompt or ""


def resolve_h3_prompt_variant(ai_tool: Any, task_key: Optional[str] = None) -> Optional[str]:
    """首帧参考混合 → KFRef；参考生视频 → Ref2VA；仅首帧 → I2VA；有尾帧 → FL2VA；无可用输入 → None。

    KFRef 必须先返回。否则两张参考图会被后面的首尾帧兜底读成 FL2VA，Picture 2 会被写成尾帧。
    """
    if task_key == DriverKey.MINIMAX_H3_KEYFRAME_REF_TO_VIDEO:
        counts = resolve_h3_reference_asset_counts(ai_tool)
        if counts["images"] or counts["audios"]:
            return H3_PROMPT_OPTIMIZE_VARIANT_KF_REF
        return None
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
    if variant == H3_PROMPT_OPTIMIZE_VARIANT_KF_REF:
        path = _KFREF_TEMPLATE_PATH
    elif variant == H3_PROMPT_OPTIMIZE_VARIANT_REF2VA:
        path = _REF2VA_TEMPLATE_PATH
    else:
        path = _TEMPLATE_PATH
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


def _kfref_roles(keyframe_slots: Optional[Dict[str, Any]], ref_counts: Optional[Dict[str, int]]) -> Dict[str, str]:
    slots = keyframe_slots if isinstance(keyframe_slots, dict) else {}
    roles = slots.get("roles") if isinstance(slots.get("roles"), dict) else {}
    if any(roles.get(f"picture_{index}") for index in (1, 2, 3)):
        return {f"picture_{index}": str(roles.get(f"picture_{index}") or _H3_KF_ROLE_EMPTY) for index in (1, 2, 3)}
    images = int((ref_counts or {}).get("images") or 0)
    return {
        f"picture_{index}": _H3_KF_ROLE_REFERENCE if index <= images else _H3_KF_ROLE_EMPTY
        for index in (1, 2, 3)
    }


def kfref_keyframe_clause(index: int, role: str, duration: float) -> Optional[str]:
    """混合模型要求大模型逐字写入的首帧或尾帧原句。参考槽不产生原句。"""
    if role == _H3_KF_ROLE_START:
        return f"<Picture {index}> is the EXACT starting key frame at 0.00 seconds."
    if role == _H3_KF_ROLE_END:
        seconds = f"{float(duration or 5):.2f}"
        return f"<Picture {index}> is the EXACT ending key frame at {seconds} seconds (ref_image{index})."
    return None


def kfref_required_clauses(
    keyframe_slots: Optional[Dict[str, Any]],
    duration: Optional[float],
) -> List[str]:
    """按槽位角色收集必须原样出现在 KFRef 结果里的句子。"""
    roles: Dict[str, Any] = {}
    if isinstance(keyframe_slots, dict) and isinstance(keyframe_slots.get("roles"), dict):
        roles = keyframe_slots["roles"]
    clauses = []
    for index in (1, 2, 3):
        clause = kfref_keyframe_clause(index, str(roles.get(f"picture_{index}") or ""), duration or 5)
        if clause:
            clauses.append(clause)
    return clauses


_KFREF_AUDIO_SPOKEN = (
    "<Audio 1> is a reference audio for voice timbre, vocal identity, speaking tone, "
    "rhythm, intonation, and lip-sync pacing."
)


def _kfref_audio_line(audios: int) -> str:
    """有参考音频（此时必有台词）保留对口型句；无参考音频写明不要编造。

    无对白镜头一律按 0 路音频下指令（调用方已强制归零）：
    <Audio N> 只有绑到要说新台词的角色身上才是音色参考，没有目标台词时
    连上的语音会被当成成片声音，两路人声叠环境音发糊（线上案例）。
    """
    if audios <= 0:
        return "没有参考音频，不要编造 <Audio N>。"
    stance = "this shot has spoken lines"
    sentence = _KFREF_AUDIO_SPOKEN
    if audios >= 2:
        count = (
            "有 2 个参考音频。第一段写成 <Audio 1>，第二段写成 <Audio 2>。"
            "每一段都照抄下面这一句，只改编号。"
            "不要写 <Audio 3>，也不要写 <audio_N>。"
        )
    else:
        count = "只有 1 个参考音频，写成 <Audio 1>。不要写 <Audio 2>，也不要写 <audio_2>。"
    return f"{stance}。{count}\n{sentence}\n"


def _build_kfref_instruction(
    keyframe_slots: Optional[Dict[str, Any]],
    ref_counts: Optional[Dict[str, int]],
    duration: float,
    has_dialogue: bool = False,
) -> str:
    """按真实槽位写 KFRef 指令。原句交给大模型照抄，代码不拼进优化结果。"""
    roles = _kfref_roles(keyframe_slots, ref_counts)
    lines = []
    has_keyframe = False
    has_reference = False
    for index in (1, 2, 3):
        role = roles.get(f"picture_{index}") or _H3_KF_ROLE_EMPTY
        clause = kfref_keyframe_clause(index, role, duration)
        if role == _H3_KF_ROLE_START and clause:
            lines.append(
                f"{clause} The video must begin pixel-consistently with <Picture {index}> "
                "for scene composition. The opening frame must not be reinterpreted or changed. "
                "Do not lock in the source-image pose as mandatory action for the video sequence. "
                "Copy the first sentence exactly."
            )
            has_keyframe = True
        elif role == _H3_KF_ROLE_END and clause:
            lines.append(
                f"{clause} The video must end pixel-consistently with <Picture {index}> "
                "for scene composition, camera framing, character positions, poses, spacing, props, and the environment. "
                "The closing frame must not be reinterpreted or changed. "
                f"Do not treat <Picture {index}> as a separate character-only reference whose background can be discarded; "
                "it is the target last frame. Copy the first sentence exactly."
            )
            has_keyframe = True
        elif role == _H3_KF_ROLE_REFERENCE:
            lines.append(
                f"<Picture {index}> is a character, scene, or prop reference. "
                "It is not a starting key frame and not an ending key frame. "
                f"Do not inherit the background, lighting, or camera framing from <Picture {index}>."
            )
            has_reference = True
        else:
            lines.append(f"Do not mention <Picture {index}>. This slot has no image.")
    audios = min(int((ref_counts or {}).get("audios") or 0), MAX_VOICE_REFERENCE_AUDIOS)
    if not has_dialogue:
        # 无对白镜头按 0 路音频下指令：音频文件也不会上传（KFRef 驱动共用同一
        # 引号台词判断），前缀去掉 audio reference，防止模型编造 <Audio N>。
        audios = 0
    audio_line = _kfref_audio_line(audios)
    prefix_parts = []
    if has_keyframe:
        prefix_parts.append("keyframe completion")
    if has_reference:
        prefix_parts.append("reference generation")
    if audios > 0:
        prefix_parts.append("audio reference")
    prefix = " + ".join(prefix_parts) if prefix_parts else "reference generation"
    seconds = f"{float(duration or 5):.2f}"
    has_end = any(roles.get(f"picture_{index}") == _H3_KF_ROLE_END for index in (1, 2, 3))
    # 原文常写「固定运镜」和起始姿势。大模型若把这些写进结尾，视频模型会停在首帧构图，尾帧图对不上。
    end_override = ""
    if has_end:
        end_override = (
            "存在结束关键帧时，镜头必须从起始画面走到结束关键帧。"
            "不要把起始姿势写成结尾姿势。"
            "原文里的「固定运镜」不能写成 fixed camera、camera locked，也不能把起始景别保持到结尾。"
            "不要用文字规定结尾的景别、机位和人物姿势。结尾画面只由结束关键帧那张图决定。"
            "镜头正文只写两帧之间的动作和台词，并写明视频停在该结束关键帧上。\n"
        )
    return (
        "下面是原本视频的提示词。这是关键帧与参考图混合生成，不要使用 Ref2VA 的六段标题。"
        f"镜头正文前写类型前缀，只保留实际存在的部分：[{prefix}]。"
        "描述用英文。台词、歌词和画面上的文字放在 <d> 里，保持原来的语言。"
        "每个有图片的槽位单独成段。起始关键帧和结束关键帧的第一句必须与下面给出的英文原句逐字相同，"
        "不得改写 EXACT、时间、大小写或 ref_image 编号。\n"
        + "\n".join(lines)
        + "\n"
        + end_override
        + audio_line
        + "本工作流没有参考视频槽，不要写 <video_N>。"
        + f"目标视频时长为 {seconds} 秒，请修改为符合以上规范的提示词。"
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


def has_quoted_dialogue(text: str) -> bool:
    """原文是否含引号包裹的 CJK 台词片段。

    音色注入、KFRef 驱动上传与提示词优化共用这一口径判断镜头有无对白：
    无对白的 KFRef 镜头不上传音色文件、音频槽填 None、优化指令按 0 路音频写。
    """
    return bool(_extract_quoted_cjk_spans(text))


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
        f"若它们是角色说出的台词、旁白/画外音口播、唱出的歌词或画面中的可见文字,"
        f"必须逐字保留在 <d> 内(语言标签写 [{language}]),严禁翻译或改写;"
        f"若它们只是动作、氛围、术语等描述性用法,则正常按英文规范转写。"
    )


def _build_no_dialogue_note() -> str:
    """原文无引号台词时的反幻觉提示:防止 LLM 仿照模板示例虚构角色对白。

    线上案例(ai_tools 231):原文仅写"音频1是李卫国的音色样本,角色说话时请保持相同音色",
    Ref2VA 模板的 few-shot 示例(音色参考+角色开口说台词)诱导 LLM 编造
    "早上好,新的一天开始了。"并提交给视频模型,成片角色凭空开口说话。
    """
    return (
        "原始提示词中没有任何引号标注的台词。"
        "只有当原文明确写出角色说出或唱出的具体话语时,才把该话语逐字放入 <d> 并标注准确的语言标签;"
        "除此之外严禁虚构、编造或补充任何对白、歌词或角色开口说话的行为——"
        "音色参考仅约束角色开口说话时应使用的音色,绝不代表角色必须说话;"
        "若原文没有任何台词,输出中不得出现 <d> 标签。"
    )


def build_h3_optimize_user_message(
    original_prompt: str,
    variant: str,
    duration: float,
    template: Optional[str] = None,
    ref_counts: Optional[Dict[str, int]] = None,
    keyframe_slots: Optional[Dict[str, Any]] = None,
) -> str:
    guide = template if template is not None else load_h3_prompt_template(variant)
    quoted_spans = _extract_quoted_cjk_spans(original_prompt)
    if variant == H3_PROMPT_OPTIMIZE_VARIANT_KF_REF:
        instruction = _build_kfref_instruction(
            keyframe_slots,
            ref_counts,
            duration,
            has_dialogue=bool(quoted_spans),
        )
    elif variant == H3_PROMPT_OPTIMIZE_VARIANT_REF2VA:
        instruction = _build_ref2va_instruction(ref_counts, duration)
    elif variant == H3_PROMPT_OPTIMIZE_VARIANT_FL2VA:
        instruction = _FL2VA_INSTRUCTION.format(duration=float(duration or 5))
    else:
        instruction = _I2VA_INSTRUCTION
    if quoted_spans:
        instruction = f"{instruction}\n{_build_dialogue_fidelity_note(quoted_spans)}"
    else:
        instruction = f"{instruction}\n{_build_no_dialogue_note()}"
    body = (original_prompt or "").strip() or "(empty original prompt)"
    return f"{guide.rstrip()}\n\n{instruction}\n\n{body}\n"


def strip_prompt_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_RE.sub("", cleaned).strip()
    return cleaned


def validate_h3_optimized_prompt(
    text: str,
    variant: str,
    *,
    keyframe_slots: Optional[Dict[str, Any]] = None,
    duration: Optional[float] = None,
    forbid_audio_refs: bool = False,
) -> bool:
    prompt = strip_prompt_fences(text)
    if not prompt:
        return False
    lowered = prompt.lower()
    # 仅在 KFRef 且原文无引号台词时开启：无对白镜头连上的语音会被当成成片声音，
    # 优化结果不得出现任何音频引用；有台词镜头本来就要写 <Audio 1>，不能开。
    if forbid_audio_refs and "<audio" in lowered:
        return False
    if variant == H3_PROMPT_OPTIMIZE_VARIANT_KF_REF:
        # 只接受大模型逐字写出的首尾帧原句。不在这里补句子。
        clauses = kfref_required_clauses(keyframe_slots, duration)
        return bool(clauses) and all(clause in prompt for clause in clauses)
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
