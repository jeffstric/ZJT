# -*- coding: utf-8 -*-
"""剧本朗读时长/字数预算共享函数（生成端与拆分端共用的单一实现）。

速率常量见 config/constant.py ScriptDurationRateConstants；前端
web/js/storyboard/render.js 与 web/js/script_node.js 保有同公式 JS 副本，
数值改动需三处同步（tests/js/test_storyboard_script_split_static.js 防漂移）。
见 docs/script/story_writer_duration_budget.md。
"""
import re
from typing import Optional

from config.constant import ScriptDurationRateConstants

# CJK 字符（含假名）：按中文朗读速率估算；其余字符按拉丁速率估算。
# 与 llm/script_parser.py 的 _CJK_CHAR_RE 保持一致（修改时同步）。
_CJK_CHAR_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3040-\u30ff]')


def rate_per_second(text: str) -> float:
    """按 CJK 字符占比混合朗读速率（字/秒）。

    纯中文 4.5 字/秒、纯拉丁 11 字符/秒，中英混排按占比线性混合。
    """
    chars = [ch for ch in (text or "") if not ch.isspace()]
    if not chars:
        return ScriptDurationRateConstants.CJK_CHARS_PER_SECOND
    cjk_count = sum(1 for ch in chars if _CJK_CHAR_RE.match(ch))
    ratio = cjk_count / len(chars)
    return (
        ratio * ScriptDurationRateConstants.CJK_CHARS_PER_SECOND
        + (1 - ratio) * ScriptDurationRateConstants.LATIN_CHARS_PER_SECOND
    )


def estimate_duration_seconds(text: str) -> float:
    """按非空白字符数估算全文朗读时长（秒）。"""
    chars = [ch for ch in (text or "") if not ch.isspace()]
    if not chars:
        return 0.0
    return round(len(chars) / rate_per_second(text), 1)


def estimate_dialogue_seconds(dialogue_text: str) -> float:
    """按台词文本（调用方已过滤掉画面描写等非口播内容）估算朗读时长（秒）。"""
    return estimate_duration_seconds(dialogue_text)


def dialogue_char_budget(
    target_seconds: float,
    rate: Optional[float] = None,
) -> int:
    """给定目标片长（秒），换算台词字数预算。

    台词预算秒数 = 片长 × DIALOGUE_SHARE；字数 = 预算秒数 × 速率。
    rate 缺省按纯中文口径（4.5 字/秒），中英混排剧本可传
    rate_per_second(全文) 的混合速率。
    """
    if target_seconds is None or target_seconds <= 0:
        return 0
    effective_rate = (
        float(rate)
        if rate and rate > 0
        else ScriptDurationRateConstants.CJK_CHARS_PER_SECOND
    )
    budget_seconds = float(target_seconds) * ScriptDurationRateConstants.DIALOGUE_SHARE
    return int(round(budget_seconds * effective_rate))


def budget_tolerance_upper(target_seconds: float, rate: Optional[float] = None) -> int:
    """台词字数预算的容差上限：预算 × (1 + DIALOGUE_BUDGET_TOLERANCE)。

    超过该值生成端（story-writer 工具层）要求删减。
    """
    budget = dialogue_char_budget(target_seconds, rate=rate)
    return int(round(budget * (1 + ScriptDurationRateConstants.DIALOGUE_BUDGET_TOLERANCE)))
