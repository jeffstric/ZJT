"""
内容审核 / 违禁内容错误识别与友好提示（方案 A）

将上游供应商返回的英文 code/message 识别为审核类错误，并生成可写入
ai_tools.message、经 /api/get-status 的 reason 展示的中文文案。

设计文档：docs/image/content_moderation_error_design.md
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


SOURCE_PROMPT = "prompt"
SOURCE_REFERENCE_IMAGE = "reference_image"
SOURCE_OUTPUT = "output"
SOURCE_COPYRIGHT = "copyright"
SOURCE_GENERAL = "general"

FRIENDLY_PREFIX = "内容审核未通过"

_ERROR_CODE_SOURCE = {
    "moderation_blocked": SOURCE_GENERAL,
    "invalid_prompt": SOURCE_PROMPT,
    "content_filter": SOURCE_GENERAL,
    "content_policy_violation": SOURCE_GENERAL,
    "content_policy": SOURCE_GENERAL,
    "inputtextsensitivecontentdetected": SOURCE_PROMPT,
    "inputimagesensitivecontentdetected": SOURCE_REFERENCE_IMAGE,
    "inputvideosensitivecontentdetected": SOURCE_REFERENCE_IMAGE,
    "outputtextsensitivecontentdetected": SOURCE_OUTPUT,
    "outputimagesensitivecontentdetected": SOURCE_OUTPUT,
    "outputvideosensitivecontentdetected": SOURCE_OUTPUT,
    "sensitivecontentdetected": SOURCE_GENERAL,
    "textsensitivecontentdetected": SOURCE_PROMPT,
    "imagesensitivecontentdetected": SOURCE_REFERENCE_IMAGE,
}

_GEMINI_BLOCK_REASONS = {
    "image_safety": (SOURCE_OUTPUT, ["safety"]),
    "image_prohibited_content": (SOURCE_PROMPT, ["prohibited"]),
    "prohibited_content": (SOURCE_PROMPT, ["prohibited"]),
    "image_other": (SOURCE_COPYRIGHT, ["copyright"]),
    "image_recitation": (SOURCE_COPYRIGHT, ["copyright"]),
    "recitation": (SOURCE_COPYRIGHT, ["copyright"]),
}

_SAFETY_VIOLATION_LABELS = {
    "violence": "暴力",
    "sexual": "色情",
    "self_harm": "自残",
    "self-harm": "自残",
    "hate": "仇恨",
    "harassment": "骚扰",
    "illegal": "违法",
    "drugs": "毒品",
    "weapon": "武器",
    "weapons": "武器",
    "child": "未成年人相关",
    "political": "政治敏感",
    "safety": "安全策略",
    "prohibited": "违禁内容",
    "copyright": "版权/商标",
    "trademark": "版权/商标",
}

_MESSAGE_SOURCE_HINTS = (
    (SOURCE_COPYRIGHT, (
        "copyright",
        "trademark",
        "image_other",
        "image_recitation",
        "recitation",
        "版权",
        "商标",
    )),
    (SOURCE_OUTPUT, (
        "output image",
        "outputimage",
        "output video",
        "outputvideo",
        "output text",
        "generated image was blocked",
        "generated image contains",
        "generated image",
        "output may contain",
        "image_safety",
        "生成结果",
        "输出图片",
        "输出图像",
    )),
    (SOURCE_REFERENCE_IMAGE, (
        "input image",
        "inputimage",
        "reference image",
        "image sensitive",
        "参考图",
        "输入图片",
        "输入图像",
    )),
    (SOURCE_PROMPT, (
        "invalid_prompt",
        "input text",
        "inputtext",
        "modify your prompt",
        "please modify your prompt",
        "text sensitive",
        "text risk",
        "image_prohibited",
        "prohibited content",
        "prohibited material",
        # Gemini duomi 输入侧拒绝话术（2026-08 日志样本）
        "sensitive_words",
        "considered unsafe",
        "candidate stopped before producing",
        "文本",
        "提示词",
    )),
)

_MODERATION_MESSAGE_MARKERS = (
    "safety system",
    "safety_violations",
    "safety policy",
    "moderation_blocked",
    "moderation",
    "content policy",
    "content_filter",
    "sensitive content",
    "sensitive information",
    "sensitivecontent",
    # Gemini duomi / Grok 渠道原始话术（2026-08 日志样本）
    "sensitive_words",
    "unsafe",
    "content security",
    "gemini blocked",
    "candidate stopped before producing",
    "rejected by the safety",
    "image generation blocked",
    "generation blocked",
    "generation was stopped",
    "blocked due to",
    "prohibited content",
    "prohibited material",
    "copyright",
    "trademark",
    "image_safety",
    "image_other",
    "image_prohibited",
    "policy violation",
    "violat",
    "内容安全",
    "内容审核",
    "敏感内容",
    "敏感信息",
    "违禁",
    "违规内容",
    "审核未通过",
    "审核不通过",
    "版权",
    "商标",
)

_SOURCE_HINT_MESSAGES = {
    SOURCE_PROMPT: f"{FRIENDLY_PREFIX}：提示词包含敏感/违禁内容，请修改提示词后重试",
    SOURCE_REFERENCE_IMAGE: f"{FRIENDLY_PREFIX}：参考图片包含敏感内容，请更换参考图后重试",
    SOURCE_OUTPUT: f"{FRIENDLY_PREFIX}：生成结果可能包含敏感内容，请调整提示词或参考图后重试",
    SOURCE_COPYRIGHT: f"{FRIENDLY_PREFIX}（版权/商标）：提示词或参考内容可能涉及受保护形象/标识，请修改后重试",
    SOURCE_GENERAL: f"{FRIENDLY_PREFIX}：请求被安全系统拦截，请检查提示词和参考图后重试",
}

_SAFETY_VIOLATIONS_RE = re.compile(
    r"safety_violations\s*=\s*\[([^\]]*)\]",
    re.IGNORECASE,
)
_GEMINI_BLOCK_RE = re.compile(
    r"(?:Gemini\s+)?image\s+generation\s+blocked\s*\[([^\]]+)\]",
    re.IGNORECASE,
)
_API_ERROR_CODE_RE = re.compile(
    r"API\s*错误\s*\[([^\]]+)\]",
    re.IGNORECASE,
)
_CODE_IN_TEXT_RE = re.compile(
    r"\b(moderation_blocked|invalid_prompt|content_filter|"
    r"channel:image_generation_failed|"
    r"OutputImageSensitiveContentDetected|InputImageSensitiveContentDetected|"
    r"InputTextSensitiveContentDetected|OutputTextSensitiveContentDetected|"
    r"OutputVideoSensitiveContentDetected|SensitiveContentDetected|"
    r"IMAGE_SAFETY|IMAGE_OTHER|IMAGE_PROHIBITED_CONTENT|PROHIBITED_CONTENT)\b",
    re.IGNORECASE,
)


def _normalize_code(code: Any) -> str:
    if code is None:
        return ""
    return str(code).strip()


def _code_key(code: str) -> str:
    return (
        code.strip()
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace(":", "")
    )


def is_content_moderation_user_message(message: Optional[str]) -> bool:
    """判断字符串是否为本模块生成的友好审核文案（驱动 USER 分支放行用）。"""
    if not message or not isinstance(message, str):
        return False
    return message.startswith(FRIENDLY_PREFIX)


def _infer_source_from_code(code: str) -> Optional[str]:
    if not code:
        return None
    raw_key = code.strip().lower()
    if raw_key in _ERROR_CODE_SOURCE:
        return _ERROR_CODE_SOURCE[raw_key]
    compact = _code_key(code)
    for known, source in _ERROR_CODE_SOURCE.items():
        if _code_key(known) == compact:
            return source
    if "input" in compact and "text" in compact:
        return SOURCE_PROMPT
    if "input" in compact and ("image" in compact or "video" in compact):
        return SOURCE_REFERENCE_IMAGE
    if "output" in compact and ("image" in compact or "video" in compact or "text" in compact):
        return SOURCE_OUTPUT
    if "prompt" in compact:
        return SOURCE_PROMPT
    if "moderation" in compact or "sensitive" in compact or "contentfilter" in compact:
        return SOURCE_GENERAL
    return None


def parse_gemini_block_reason(message: str) -> Optional[str]:
    if not message:
        return None
    match = _GEMINI_BLOCK_RE.search(message)
    if not match:
        return None
    return match.group(1).strip()


def _infer_source_from_message(message: str) -> Optional[str]:
    if not message:
        return None
    lower = message.lower()

    gemini_reason = parse_gemini_block_reason(message)
    if gemini_reason:
        mapped = _GEMINI_BLOCK_REASONS.get(gemini_reason.lower())
        if mapped:
            source, _ = mapped
            if source == SOURCE_COPYRIGHT or "copyright" in lower or "trademark" in lower:
                return SOURCE_COPYRIGHT if (
                    source == SOURCE_COPYRIGHT
                    or "copyright" in lower
                    or "trademark" in lower
                ) else source
            return source

    for source, hints in _MESSAGE_SOURCE_HINTS:
        for hint in hints:
            if hint.lower() in lower:
                return source
    return None


def _is_moderation_message(message: str) -> bool:
    if not message:
        return False
    lower = message.lower()
    return any(marker in lower for marker in _MODERATION_MESSAGE_MARKERS)


def parse_safety_violations(message: str) -> List[str]:
    if not message:
        return []
    parts: List[str] = []
    match = _SAFETY_VIOLATIONS_RE.search(message)
    if match:
        raw = match.group(1).strip()
        if raw:
            for item in raw.split(","):
                token = item.strip().strip("\"'").lower()
                if token:
                    parts.append(token)

    gemini_reason = parse_gemini_block_reason(message)
    if gemini_reason:
        mapped = _GEMINI_BLOCK_REASONS.get(gemini_reason.lower())
        if mapped:
            _, tags = mapped
            parts.extend(tags)
        lower = message.lower()
        if ("copyright" in lower or "trademark" in lower) and "copyright" not in parts:
            parts.append("copyright")

    seen = set()
    ordered: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def _format_violation_labels(violations: list) -> str:
    labels = [_SAFETY_VIOLATION_LABELS.get(v, v) for v in violations]
    seen = set()
    ordered = []
    for label in labels:
        if label not in seen:
            seen.add(label)
            ordered.append(label)
    return "、".join(ordered)


def _source_action_hint(source: str) -> str:
    if source == SOURCE_PROMPT:
        return "提示词包含敏感/违禁内容，请修改提示词后重试"
    if source == SOURCE_REFERENCE_IMAGE:
        return "参考图片包含敏感内容，请更换参考图后重试"
    if source == SOURCE_OUTPUT:
        return "生成结果可能包含敏感内容，请调整提示词或参考图后重试"
    if source == SOURCE_COPYRIGHT:
        return "提示词或参考内容可能涉及受保护形象/标识，请修改后重试"
    return "请检查提示词和参考图后重试"


def classify_content_moderation(
    error_code: Any = None,
    error_message: Any = None,
    error_type: Any = None,
) -> Optional[Dict[str, Any]]:
    """
    判断是否为内容审核错误并分类。

    Returns:
        None 或 {
            "source", "violations", "error_code", "friendly_message"
        }
    """
    code = _normalize_code(error_code)
    message = _normalize_code(error_message)
    err_type = _normalize_code(error_type).lower()

    source = _infer_source_from_code(code)
    is_moderation = source is not None

    if not is_moderation and err_type in (
        "image_generation_user_error",
        "content_policy_violation",
        "moderation_error",
        "channel_error",
    ):
        if err_type == "channel_error":
            is_moderation = _is_moderation_message(message)
        else:
            is_moderation = True

    if not is_moderation and _is_moderation_message(message):
        is_moderation = True

    if not is_moderation and "image_generation_failed" in code.lower():
        is_moderation = _is_moderation_message(message)

    if not is_moderation:
        return None

    msg_source = _infer_source_from_message(message)
    if source in (None, SOURCE_GENERAL) and msg_source:
        source = msg_source
    elif source is None:
        source = SOURCE_GENERAL

    if code.lower() == "invalid_prompt":
        source = SOURCE_PROMPT

    if message and ("copyright" in message.lower() or "trademark" in message.lower()):
        if parse_gemini_block_reason(message) or source == SOURCE_COPYRIGHT:
            source = SOURCE_COPYRIGHT

    violations = parse_safety_violations(message)

    if source == SOURCE_COPYRIGHT:
        friendly = _SOURCE_HINT_MESSAGES[SOURCE_COPYRIGHT]
    else:
        friendly = _SOURCE_HINT_MESSAGES.get(source, _SOURCE_HINT_MESSAGES[SOURCE_GENERAL])
        if violations:
            labels = _format_violation_labels(violations)
            if labels:
                friendly = f"{FRIENDLY_PREFIX}（{labels}）：{_source_action_hint(source)}"

    return {
        "source": source,
        "violations": violations,
        "error_code": code,
        "friendly_message": friendly,
    }


def format_user_facing_moderation_error(
    error_code: Any = None,
    error_message: Any = None,
    error_type: Any = None,
) -> Optional[str]:
    info = classify_content_moderation(
        error_code=error_code,
        error_message=error_message,
        error_type=error_type,
    )
    if not info:
        return None
    return info["friendly_message"]


def extract_api_error_fields(error_payload: Any) -> Tuple[str, str, str]:
    if isinstance(error_payload, dict):
        code = error_payload.get("code") or error_payload.get("error_code") or ""
        message = (
            error_payload.get("message")
            or error_payload.get("msg")
            or error_payload.get("error")
            or ""
        )
        err_type = error_payload.get("type") or ""
        if isinstance(message, dict):
            message = message.get("message") or str(message)
        return _normalize_code(code), _normalize_code(message), _normalize_code(err_type)

    text = _normalize_code(error_payload)
    code = ""
    m = _API_ERROR_CODE_RE.search(text)
    if m:
        code = m.group(1).strip()
    else:
        m2 = _CODE_IN_TEXT_RE.search(text)
        if m2:
            code = m2.group(1)
    if not code:
        gemini_reason = parse_gemini_block_reason(text)
        if gemini_reason:
            code = gemini_reason
    return code, text, ""


def build_user_error_from_api_error(
    error_payload: Any,
    fallback_prefix: str = "任务提交失败",
) -> str:
    code, message, err_type = extract_api_error_fields(error_payload)
    friendly = format_user_facing_moderation_error(
        error_code=code,
        error_message=message,
        error_type=err_type,
    )
    if friendly:
        return friendly

    if code and message:
        return f"{fallback_prefix}: [{code}] {message}"
    if message:
        return f"{fallback_prefix}: {message}"
    if code:
        return f"{fallback_prefix}: {code}"
    return f"{fallback_prefix}: 未知错误"


def rewrite_failure_reason_if_moderation(reason: str) -> str:
    if not reason or not isinstance(reason, str):
        return reason

    if reason.startswith(FRIENDLY_PREFIX):
        return reason

    code, message, err_type = extract_api_error_fields(reason)
    if "channel_error" in reason.lower() and not err_type:
        err_type = "channel_error"
    friendly = format_user_facing_moderation_error(
        error_code=code,
        error_message=message or reason,
        error_type=err_type,
    )
    if friendly:
        return friendly
    return reason


def should_suggest_reduce_violation(source: Optional[str] = None, message: Optional[str] = None) -> bool:
    """
    是否建议展示「降低违规」入口（方案 D）。
    prompt / general / output 建议；reference_image 不主推。
    """
    if source in (SOURCE_PROMPT, SOURCE_GENERAL, SOURCE_OUTPUT):
        return True
    if source == SOURCE_REFERENCE_IMAGE:
        return False
    if source == SOURCE_COPYRIGHT:
        return True  # 可选改写，UI 可弱提示
    if message and isinstance(message, str):
        if message.startswith(FRIENDLY_PREFIX):
            if "参考图片" in message:
                return False
            return True
    return False
