"""IndexTTS 8 维情感向量纯函数规范化（无许可证门禁，仅做数值修复）。

门禁（是否用于 TTS / 拆分注入）在 services.dialogue_emotion 与 enterprise Provider。
"""
from __future__ import annotations

from typing import Any, List, Optional

from config.constant import EmotionVectorConstants


def normalize_emotion_vector(raw: Any) -> Optional[str]:
    """规范化为逗号分隔 8 维字符串；非法/全 0 返回 None。"""
    values = _parse_to_floats(raw)
    if values is None:
        return None

    clamped: List[float] = []
    for v in values:
        if v != v:  # NaN
            v = 0.0
        if v < 0:
            v = 0.0
        if v > EmotionVectorConstants.MAX_EACH:
            v = float(EmotionVectorConstants.MAX_EACH)
        clamped.append(float(v))

    total = sum(clamped)
    if total <= 0:
        return None

    max_sum = float(EmotionVectorConstants.MAX_SUM)
    if total > max_sum:
        scale = max_sum / total
        clamped = [round(v * scale, 4) for v in clamped]
        total2 = sum(clamped)
        if total2 > max_sum and total2 > 0:
            scale2 = max_sum / total2
            clamped = [round(v * scale2, 4) for v in clamped]

    if sum(clamped) <= 0:
        return None
    return ",".join(f"{v:.4f}" for v in clamped)


def parse_emotion_vector_list(raw: Any) -> List[float]:
    """解析为 8 维 list，失败返回全 0。"""
    values = _parse_to_floats(raw)
    if not values:
        return [0.0] * EmotionVectorConstants.DIM
    return values


def _parse_to_floats(raw: Any) -> Optional[List[float]]:
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        parts = [p.strip() for p in text.split(",") if p.strip() != ""]
        if len(parts) != EmotionVectorConstants.DIM:
            return None
        try:
            return [float(p) for p in parts]
        except (TypeError, ValueError):
            return None
    if isinstance(raw, dict):
        labels = EmotionVectorConstants.LABELS
        try:
            return [
                float(raw.get(label, raw.get(str(i), 0)) or 0)
                for i, label in enumerate(labels)
            ]
        except (TypeError, ValueError):
            return None
    if isinstance(raw, (list, tuple)):
        if len(raw) != EmotionVectorConstants.DIM:
            return None
        try:
            return [float(x) for x in raw]
        except (TypeError, ValueError):
            return None
    return None
