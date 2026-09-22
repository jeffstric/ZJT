# -*- coding: utf-8 -*-
"""生成端时长预算（docs/script/story_writer_duration_budget.md）单元测试。

覆盖：
- ScriptDurationRateConstants 常量与 ScriptSplitConstants 旧名收敛
- utils/script_duration.py 速率/预算函数（含语言区分）
- enforce_total_duration_limit 合并循环压进容差后 dialogue_floor_exceeded_seconds
  不再假达标（2026-09-19 乌灵胶囊事故缺口回归）
- story-writer SKILL.md 预算章节静态防漂移断言
- script_writer_core.mcp_tool._build_dialogue_stats 统计与超预算 warning
"""
import os
from pathlib import Path

import pytest

from config.constant import ScriptDurationRateConstants, ScriptSplitConstants
from utils.script_duration import (
    budget_tolerance_upper,
    dialogue_char_budget,
    estimate_dialogue_seconds,
    rate_per_second,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---- 常量收敛 ----

def test_rate_constants_converged():
    assert ScriptSplitConstants.SCRIPT_DURATION_CJK_CHARS_PER_SECOND == (
        ScriptDurationRateConstants.CJK_CHARS_PER_SECOND)
    assert ScriptSplitConstants.SCRIPT_DURATION_LATIN_CHARS_PER_SECOND == (
        ScriptDurationRateConstants.LATIN_CHARS_PER_SECOND)
    assert ScriptSplitConstants.TOTAL_DURATION_DIALOGUE_SHARE == (
        ScriptDurationRateConstants.DIALOGUE_SHARE)


# ---- 速率与预算 ----

def test_rate_per_second_language_mix():
    # 纯中文 4.5 字/秒
    assert rate_per_second("睡前") == pytest.approx(4.5)
    # 纯拉丁 11 字符/秒
    assert rate_per_second("abcde") == pytest.approx(11.0)
    # 空白不计入、空文本回退中文口径
    assert rate_per_second("a b c") == pytest.approx(11.0)
    assert rate_per_second("") == pytest.approx(
        ScriptDurationRateConstants.CJK_CHARS_PER_SECOND)
    # 混排：CJK 与拉丁各占一半 → (4.5 + 11) / 2
    assert rate_per_second("睡a") == pytest.approx((4.5 + 11.0) / 2)
    assert rate_per_second("睡abc") == pytest.approx(0.25 * 4.5 + 0.75 * 11.0)


def test_dialogue_char_budget_tiers():
    # 速查表：1/2/3 分钟档中文台词预算
    assert dialogue_char_budget(60) == 162
    assert dialogue_char_budget(120) == 324
    assert dialogue_char_budget(180) == 486
    # 英文口径（11 字符/秒）：1 分钟 = 60×0.6×11 = 396
    assert dialogue_char_budget(60, rate=11.0) == 396
    # 非法输入
    assert dialogue_char_budget(0) == 0
    assert dialogue_char_budget(-5) == 0


def test_budget_tolerance_upper():
    assert budget_tolerance_upper(180) == int(round(486 * 1.2))


def test_estimate_dialogue_seconds():
    # 45 个 CJK 字 ÷ 4.5 = 10s
    assert estimate_dialogue_seconds("睡" * 45) == pytest.approx(10.0)


# ---- enforce_total_duration_limit 合并循环 floor 上报缺口 ----

def _shot(number, duration, dialogue=None):
    shot = {
        "shot_number": number,
        "shot_id": f"s{number:03d}",
        "duration": duration,
    }
    if dialogue is not None:
        shot["dialogue"] = [{"character_id": "narrator", "text": dialogue}]
    return shot


def _group(group_id, shots):
    return {"group_id": group_id, "shots": shots}


def test_enforce_merge_into_tolerance_still_reports_dialogue_floor():
    """事故场景回归：合并把总时长压进容差区间，但镜头台词下限之和远超目标。

    旧实现 total<=cap 时直接跳过上报，报告显示假达标；修复后必须上报
    dialogue_floor_exceeded_seconds（下限与当前总时长的差额）。
    """
    from llm.script_parser import enforce_total_duration_limit

    # 两个镜头台词不同（合并按 JSON 去重，相同文本不会重复拼入）
    parsed = {
        "shot_groups": [
            _group("g1", [
                _shot(1, 30.0, "熬" * 90),  # 台词下限 20s
                _shot(2, 30.0),             # 无台词：压缩后成为合并吸收对象
                _shot(3, 30.0, "夜" * 90),  # 台词下限 20s
            ]),
        ],
        "total_duration": 90,
    }
    report = enforce_total_duration_limit(parsed, 20.0)
    total = sum(s["duration"] for g in parsed["shot_groups"] for s in g["shots"])
    cap = 20.0 * (1 + ScriptSplitConstants.TOTAL_DURATION_TOLERANCE)
    # 合并把 3 镜并为 1 镜，总时长已进容差区间
    assert total <= cap
    # 但台词物理下限 40s 仍超目标 20s，必须上报
    assert report["dialogue_floor_exceeded_seconds"] == pytest.approx(40.0 - total)


def test_enforce_floor_report_keeps_over_cap_semantics():
    """原有语义保持：压不进容差（total>cap）时仍报 total-cap。"""
    from llm.script_parser import enforce_total_duration_limit

    # 每组仅 1 个镜头（无可合并对象），台词下限把总时长托在 60s
    parsed = {
        "shot_groups": [
            _group("g1", [_shot(1, 30.0, "甲" * 90)]),
            _group("g2", [_shot(2, 30.0, "乙" * 90)]),
            _group("g3", [_shot(3, 30.0, "丙" * 90)]),
        ],
        "total_duration": 90,
    }
    report = enforce_total_duration_limit(parsed, 20.0)
    total = sum(s["duration"] for g in parsed["shot_groups"] for s in g["shots"])
    cap = 20.0 * (1 + ScriptSplitConstants.TOTAL_DURATION_TOLERANCE)
    assert total > cap
    assert report["dialogue_floor_exceeded_seconds"] == pytest.approx(round(total - cap, 1))


# ---- SKILL.md 预算章节静态防漂移 ----

def test_story_writer_skill_contains_budget_rules():
    skill = (
        PROJECT_ROOT / "script_writer_core" / "skills" / "story-writer" / "SKILL.md"
    ).read_text(encoding="utf-8")
    # 章节存在
    assert "片长与台词字数预算" in skill
    # 公式要素：0.6 占比、4.5 字/秒、11 字符/秒、1.2 容差、自检与元信息标注
    assert "0.6" in skill
    assert "4.5" in skill
    assert "11" in skill
    assert "1.2" in skill
    assert "自检" in skill
    assert "片长：约" in skill
    assert "口播字数" in skill


def test_orchestrator_sop_passes_budget():
    sop = (
        PROJECT_ROOT / "script_writer_core" / "skills" / "script-orchestrator"
        / "sops" / "sop-new-script.md"
    ).read_text(encoding="utf-8")
    assert "台词字数预算" in sop


# ---- mcp_tool._build_dialogue_stats ----

def _narration_script(chars_text, repeat):
    return f"旁白：{chars_text * repeat}\n"


def test_build_dialogue_stats_within_budget_no_warning():
    from script_writer_core.mcp_tool import _build_dialogue_stats

    content = _narration_script("睡", 480)  # 480 字 < 上限 583
    stats, warning = _build_dialogue_stats(content, 180)
    assert stats["chars"] == 480
    assert stats["estimated_seconds"] == pytest.approx(480 / 4.5, rel=0.01)
    assert stats["target_duration_seconds"] == 180
    assert stats["budget_chars"] == 486
    assert warning is None


def test_build_dialogue_stats_over_budget_warns():
    from script_writer_core.mcp_tool import _build_dialogue_stats

    # 事故原文量级：1842 字口播配 3 分钟标注
    content = _narration_script("熬", 1842)
    stats, warning = _build_dialogue_stats(content, 180)
    assert stats["chars"] == 1842
    assert warning is not None
    assert "1842" in warning
    assert "583" in warning


def test_build_dialogue_stats_no_target_keeps_stats_only():
    from script_writer_core.mcp_tool import _build_dialogue_stats

    stats, warning = _build_dialogue_stats(_narration_script("熬", 100), None)
    assert stats["chars"] == 100
    assert "target_duration_seconds" not in stats
    assert warning is None


def test_build_dialogue_stats_english_rate():
    from script_writer_core.mcp_tool import _build_dialogue_stats

    content = f"NARRATOR: {'word ' * 70}\n"  # 280 拉丁字母（空格不计）
    stats, warning = _build_dialogue_stats(content, 60)
    assert stats["chars"] == 280
    # 英文预算：60×0.6×11 = 396，上限 475
    assert stats["budget_chars"] == 396
    assert warning is None
