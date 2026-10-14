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
# 说话意图短语（未配台词的开口动作）。只列明确形态，避免误伤 speaker/speaks about 等用法。
# 视频模型见到开口动作而无 <d> 台词会自动生成无法识别的含糊语音（ai_tools 56837）。
_SPEAKING_INTENT_RE = re.compile(
    r"ready to (?:speak|say|talk|answer|reply)"
    r"|about to (?:speak|say|talk|answer|reply)"
    r"|opens? (?:his|her|their|its) mouth"
    r"|begins? to (?:speak|say|talk)"
    r"|wants? to (?:say|speak)"
    r"|准备开口|要开口|欲言又止|张嘴|开口说",
    re.IGNORECASE,
)
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


_KFREF_AUDIO_BINDING_TEMPLATE = (
    "<Audio 1> is the voice-timbre reference for <该说话人在画面中的具体描述> (S1): "
    "it provides voice timbre, vocal identity, speaking tone, rhythm, intonation, and lip-sync pacing."
)


def _kfref_audio_line(audios: int) -> str:
    """音频段条件式指令：代码只给「可用参考音频路数」事实，有无台词由 LLM 判断。

    指令拼在 LLM 调用之前，预知不了语义判断结果，因此三种情形都写给 LLM 自选：
    有台词 + N 路 → 每路写一个绑定句（绑定到说话人，多人对话各绑各的）；
    有台词 + 0 路 → 不写任何 <Audio N>，台词照进 <d>（模型自动配音）；
    无台词 → 不写任何 <Audio N>，只写环境音（无对白时连上的语音会被当成成片声音）。
    """
    if audios <= 0:
        return (
            "没有可用参考音频：无论原文有无台词，都不要写任何 <Audio N>。"
            "台词照常放进 <d>（由模型自动配音），其余只描述环境音。\n"
        )
    if audios >= 2:
        count = (
            "有 2 个可用参考音频。第一段写成 <Audio 1>，第二段写成 <Audio 2>，"
            "每一段绑定到各自的说话人。不要写 <Audio 3>，也不要写 <audio_N>。"
        )
    else:
        count = (
            "只有 1 个可用参考音频，写成 <Audio 1>，绑定到说话人。"
            "不要写 <Audio 2>，也不要写 <audio_2>。"
        )
    return (
        "先判断原文有没有角色说出或唱出的台词（引号内容是台词还是店名/标语等"
        "描述性用法，由你判断），再按下面规则写音频段：\n"
        f"- 原文有台词：{count}每个音频写一句绑定句，句式如下（编号与占位按实际改写）：\n"
        f"{_KFREF_AUDIO_BINDING_TEMPLATE}\n"
        "- 原文没有台词：不写任何 <Audio N>，只描述环境音。\n"
    )


def _kfref_speaker_binding_rules(image_prompt_note: str) -> str:
    """说话人绑定规则：视频模型靠画面描述做 grounding，锚定原料按优先级展开。"""
    note_block = ""
    if image_prompt_note:
        note_block = (
            "绑定原料（生成本分镜图片所用的画面构成，含人物站位与外观）：\n"
            f"{image_prompt_note}\n"
            "展开说话人描述时优先采用这里的站位/外观信息。\n"
        )
    return (
        "说话人绑定规则（只在写音频绑定句或台词时使用）：\n"
        "- 台词说话人按实际发声顺序分配稳定编号 (S1)、(S2)；同一个人多条台词共用同一编号。\n"
        "- 音频绑定句和台词处都用「画面描述 + (S1)」双标注，例如 "
        "\u201cThe older man in the gray jacket on the left of <Picture 1> (S1) shouts: <d>[Chinese] …</d>\u201d。\n"
        "- 锚定优先级：该角色的参考图（如 the man holding the broom in <Picture 2>）> "
        "外观特征（服装/年龄/持物）+ 画面位置（on the left / on the right）。"
        "位置词必须与外观特征一起用，不得单独作为锚。\n"
        "- 角色名（如 李卫国）对视频模型没有画面意义，禁止作为唯一锚；必须展开为上述画面描述，"
        "且描述必须能在画面中唯一定位这个人。\n"
        + note_block
    )


def _build_kfref_instruction(
    keyframe_slots: Optional[Dict[str, Any]],
    ref_counts: Optional[Dict[str, int]],
    duration: float,
    image_prompt_note: str = "",
) -> str:
    """按真实槽位写 KFRef 指令。首尾帧原句交给大模型照抄，代码不拼进优化结果。

    台词有无、音频句与类型前缀的 audio reference 段均由 LLM 按条件式指令自选
    （语义判断结果以首行 JSON 头 has_dialogue 返回，由校验与驱动消费）；
    代码只提供确定事实：图片槽位、可用参考音频路数、时长。
    """
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
    audio_line = _kfref_audio_line(audios)
    prefix_parts = []
    if has_keyframe:
        prefix_parts.append("keyframe completion")
    if has_reference:
        prefix_parts.append("reference generation")
    base_prefix = " + ".join(prefix_parts) if prefix_parts else "reference generation"
    # audio reference 段与音频绑定句同生共死（由 LLM 按台词判断自选），代码不预写
    audio_prefix_line = (
        f"类型前缀基础为 [{base_prefix}]；仅当你按音频段规则写了 <Audio N> 绑定句时，"
        "才在前缀末尾追加 \u201c + audio reference\u201d，否则前缀保持基础值。"
    )
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
        f"{audio_prefix_line}"
        "描述用英文。台词、歌词和画面上的文字放在 <d> 里，保持原来的语言。"
        "每个有图片的槽位单独成段。起始关键帧和结束关键帧的第一句必须与下面给出的英文原句逐字相同，"
        "不得改写 EXACT、时间、大小写或 ref_image 编号。\n"
        + "\n".join(lines)
        + "\n"
        + end_override
        + _kfref_speaker_binding_rules(image_prompt_note)
        + audio_line
        + "本工作流没有参考视频槽，不要写 <video_N>。"
        + f"目标视频时长为 {seconds} 秒，请修改为符合以上规范的提示词。"
        + "输出格式：第一行必须是 {\"has_dialogue\": true} 或 {\"has_dialogue\": false}"
        "（按你对原文有无台词的判断填写），然后空一行，再输出最终提示词正文；"
        "正文原样多行输出，不要再包进 JSON。\n"
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
    """原文是否含引号包裹的 CJK 台词片段（正则形态信号，兜底口径）。

    KFRef 链路的决策优先级：优化 LLM 的语义判断（has_dialogue 标记）> 本函数。
    注入侧（提交时等不了 LLM）与驱动侧无标记时（旧任务/优化禁用/回退原文）
    用本函数兜底；优化指令本身也用它生成形态提示（有无引号），语义交给 LLM。
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

    线上案例(ai_tools 56837,2026-10-14):原文"音频备注:无对白"但动作写"准备开口",
    优化结果未编台词(反幻觉生效)却原样保留了 ready to speak——视频模型见到开口
    动作而无 <d> 台词,自动生成约 2.4 秒无文本约束的含糊语音,成片出现
    "无法识别的说话声"。故说话意图动作必须一并改写为无声动作。
    """
    return (
        "原始提示词中没有任何引号标注的台词。"
        "只有当原文明确写出角色说出或唱出的具体话语时,才把该话语逐字放入 <d> 并标注准确的语言标签;"
        "除此之外严禁虚构、编造或补充任何对白、歌词或角色开口说话的行为——"
        "音色参考仅约束角色开口说话时应使用的音色,绝不代表角色必须说话;"
        "若你判断原文没有任何台词,输出中不得出现 <d> 标签;"
        "原文写有「准备开口」「要说」「欲言又止」等说话意图时,必须改写为无声动作"
        "(轻点头、深吸一口气、目光停留、嘴唇闭合不发声),不得保留任何张嘴发声的动作——"
        "视频模型见到开口动作而没有台词文本时,会自动生成一段无法识别的含糊语音。"
    )


def build_h3_optimize_user_message(
    original_prompt: str,
    variant: str,
    duration: float,
    template: Optional[str] = None,
    ref_counts: Optional[Dict[str, int]] = None,
    keyframe_slots: Optional[Dict[str, Any]] = None,
    image_prompt_note: str = "",
) -> str:
    guide = template if template is not None else load_h3_prompt_template(variant)
    quoted_spans = _extract_quoted_cjk_spans(original_prompt)
    if variant == H3_PROMPT_OPTIMIZE_VARIANT_KF_REF:
        instruction = _build_kfref_instruction(
            keyframe_slots,
            ref_counts,
            duration,
            image_prompt_note=image_prompt_note,
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


def parse_h3_optimize_kfref_output(raw: str) -> tuple:
    """解析 KFRef 优化输出的首行 JSON 头 {"has_dialogue": bool} 与提示词正文。

    协议：第一行必须是含布尔型 has_dialogue 的 JSON 对象（额外字段忽略），
    空一行后是最终提示词正文——正文原样多行文本、不进 JSON，避免长文本
    转义失败推高回退率。任一步不合法返回 (None, None)，由调用方计入结构
    错误重试；重试耗尽回退原文（has_dialogue 落 None，驱动回退正则兜底）。
    """
    text = strip_prompt_fences(raw)
    if not text:
        return None, None
    first_line, _, rest = text.partition("\n")
    try:
        header = json.loads(first_line.strip())
    except json.JSONDecodeError:
        return None, None
    if not isinstance(header, dict):
        return None, None
    flag = header.get("has_dialogue")
    if not isinstance(flag, bool):
        return None, None
    # LLM 可能把头之后的正文再包进 ```text 围栏；整体 strip 剥不到（首行是 JSON 头），
    # 必须对余下部分单独剥，否则围栏随正文通过校验进最终视频提示词。
    prompt = strip_prompt_fences(rest)
    if not prompt:
        return None, None
    return prompt, flag


def validate_h3_optimized_prompt(
    text: str,
    variant: str,
    *,
    keyframe_slots: Optional[Dict[str, Any]] = None,
    duration: Optional[float] = None,
    forbid_audio_refs: bool = False,
    forbid_dialogue: bool = False,
) -> bool:
    prompt = strip_prompt_fences(text)
    if not prompt:
        return False
    lowered = prompt.lower()
    # 仅在原文判无台词时开启（调用方传入）：无对白镜头连上的语音会被当成成片声音，
    # 优化结果不得出现任何音频引用；有台词镜头本来就要写 <Audio 1>，不能开。
    if forbid_audio_refs and "<audio" in lowered:
        return False
    # 同上只在无台词时开启：反幻觉 note 只是指令级约束，LLM 仍可能仿照模板示例
    # 编造台词；编出的 <d> 会让视频模型给角色自动配音（成片「乱说话」），
    # 这里校验拦截，重试失败后回退无 <d> 的原文。
    if forbid_dialogue and "<d>" in lowered:
        return False
    # 无台词时同样拦截「准备开口」类说话意图动作（ai_tools 56837）：开口动作
    # 会让视频模型自动生成无文本约束的含糊语音，成片出现无法识别的说话声。
    if forbid_dialogue and _SPEAKING_INTENT_RE.search(lowered):
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
    has_dialogue: Optional[bool] = None,
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
        # KFRef 的 LLM 台词语义判断；fallback（回退原文）时为 None，
        # 驱动侧见非布尔值即回退 has_quoted_dialogue 正则兜底。
        "has_dialogue": has_dialogue,
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
