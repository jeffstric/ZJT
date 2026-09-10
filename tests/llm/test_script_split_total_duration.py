"""总分镜时长控制单元测试。

覆盖 docs/script/script_split_total_duration_control.md 的三个核心函数：
- estimate_script_duration_seconds：剧本基准时长估算（语种混合速率）
- compute_segment_duration_budget_seconds：段级预算分解
- enforce_total_duration_limit：合并后确定性归一化（压缩/兜底合并）

以及 _safe_duration_multiplier（engine）与 _normalize_request_config（api）
的倍率归一化。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constant import ScriptSplitConstants
from llm.script_parser import (
    compute_segment_duration_budget_seconds,
    enforce_total_duration_limit,
    estimate_script_duration_seconds,
)


def _shot(number, duration=5.0, description="镜头"):
    return {
        "shot_id": f"s{number:03d}",
        "shot_number": number,
        "duration": duration,
        "description": f"{description}{number}",
        "dialogue": [],
        "characters_present": [],
    }


def _group(gid, shots):
    return {"group_id": gid, "group_name": gid, "shots": shots}


# ---- estimate_script_duration_seconds ----

def test_estimate_chinese_script_by_cjk_rate():
    # 270 个纯中文字 ≈ 270/4.5 = 60 秒（1 分钟剧本）
    text = "他走进房间看了看四周" * 27  # 每句 10 字
    assert abs(estimate_script_duration_seconds(text) - 60.0) < 0.5


def test_estimate_latin_script_by_latin_rate():
    text = "abcdefghij" * 100  # 1000 个纯拉丁字符
    assert abs(estimate_script_duration_seconds(text) - 1000 / 11.0) < 1.0


def test_estimate_empty_and_short_fall_to_min():
    assert estimate_script_duration_seconds("") == ScriptSplitConstants.SCRIPT_DURATION_MIN_SECONDS
    assert estimate_script_duration_seconds("   \n\t ") == ScriptSplitConstants.SCRIPT_DURATION_MIN_SECONDS
    assert estimate_script_duration_seconds("短") == ScriptSplitConstants.SCRIPT_DURATION_MIN_SECONDS


def test_estimate_ignores_whitespace():
    dense = "他走进房间看了看四周。" * 10
    spaced = "\n".join("他走进房间看了看四周。" for _ in range(10))
    assert estimate_script_duration_seconds(dense) == estimate_script_duration_seconds(spaced)


# ---- compute_segment_duration_budget_seconds ----

def test_segment_budgets_sum_close_to_target():
    script = "他走进房间看了看四周。" * 100  # 1000 字 → 约 222 秒基准
    half_a, half_b = script[:500], script[500:]
    multiplier = 2.0
    budget_a = compute_segment_duration_budget_seconds(script, half_a, multiplier)
    budget_b = compute_segment_duration_budget_seconds(script, half_b, multiplier)
    target = estimate_script_duration_seconds(script) * multiplier
    # 段字符拼接=全剧本 → 预算和应贴近目标（10% 内）
    assert abs((budget_a + budget_b) - target) / target < 0.10


def test_segment_budget_floor_and_zero_multiplier():
    script = "他走进房间看了看四周。" * 10
    assert compute_segment_duration_budget_seconds(script, "三个字", 2.0) == (
        ScriptSplitConstants.TOTAL_DURATION_SEGMENT_BUDGET_MIN_SECONDS
    )
    assert compute_segment_duration_budget_seconds(script, script, 0) == 0.0
    assert compute_segment_duration_budget_seconds(script, "", 2.0) == 0.0


# ---- enforce_total_duration_limit ----

def test_enforce_noop_when_within_tolerance():
    # 90s 在 目标100s × (1±0.15) = 85~115s 区间内 → 不干预
    parsed = {"shot_groups": [_group("g1", [_shot(1, 45.0), _shot(2, 45.0)])], "total_duration": 90}
    report = enforce_total_duration_limit(parsed, 100.0)
    assert report["applied"] is False
    assert report["direction"] == "none"
    assert parsed["shot_groups"][0]["shots"][0]["duration"] == 45.0
    assert parsed["total_duration"] == 90


def test_enforce_expands_proportionally_to_target():
    # LLM 只拆出 56s（远低于 2 倍目标 161.6s）→ 必须等比放大到目标区间
    shots = [_shot(i, d) for i, d in enumerate([5, 3, 6, 4, 6, 3, 5, 6, 10, 8], start=1)]
    parsed = {"shot_groups": [_group("g1", shots)], "total_duration": 56}
    report = enforce_total_duration_limit(parsed, 161.6)
    assert report["applied"] is True
    assert report["direction"] == "expand"
    assert report["scaled"] is True
    total = sum(s["duration"] for s in parsed["shot_groups"][0]["shots"])
    floor = 161.6 * (1 - ScriptSplitConstants.TOTAL_DURATION_TOLERANCE)
    cap = 161.6 * (1 + ScriptSplitConstants.TOTAL_DURATION_TOLERANCE)
    assert floor <= total <= cap
    assert parsed["total_duration"] == int(round(total))


def test_enforce_expand_caps_single_shot_at_max():
    # 放大后单镜头超过上限 → 截断（增加总时长靠增加镜头数，不拉长单镜头）
    shots = [_shot(1, 20.0), _shot(2, 10.0)]  # 30s → 目标 120s
    parsed = {"shot_groups": [_group("g1", shots)], "total_duration": 30}
    report = enforce_total_duration_limit(
        parsed, 120.0,
        max_shot_seconds=ScriptSplitConstants.TOTAL_DURATION_SHOT_EXPAND_MAX_SECONDS,
    )
    assert report["direction"] == "expand"
    durations = [s["duration"] for s in parsed["shot_groups"][0]["shots"]]
    assert max(durations) <= ScriptSplitConstants.TOTAL_DURATION_SHOT_EXPAND_MAX_SECONDS
    # 20s 超上限被预截断；镜头数不足全部顶格仍低于下限 → shortfall 如实汇报
    assert report["shot_max_capped"] == 2
    assert report["shortfall_seconds"] > 0


def test_enforce_expand_no_shortfall_when_enough_shots():
    # 镜头数充足时放大应无差额达到目标（30 × 5s = 150s → 目标 300s）
    shots = [_shot(i, 5.0) for i in range(1, 31)]
    parsed = {"shot_groups": [_group("g1", shots)], "total_duration": 150}
    report = enforce_total_duration_limit(
        parsed, 300.0,
        max_shot_seconds=ScriptSplitConstants.TOTAL_DURATION_SHOT_EXPAND_MAX_SECONDS,
    )
    assert report["direction"] == "expand"
    durations = [s["duration"] for s in parsed["shot_groups"][0]["shots"]]
    assert all(d == ScriptSplitConstants.TOTAL_DURATION_SHOT_EXPAND_MAX_SECONDS for d in durations)
    total = sum(durations)
    floor = 300.0 * (1 - ScriptSplitConstants.TOTAL_DURATION_TOLERANCE)
    assert total >= floor
    assert report["shortfall_seconds"] == 0.0


def test_enforce_scales_down_proportionally():
    shots = [_shot(i, 10.0) for i in range(1, 9)]  # 8 × 10s = 80s
    parsed = {"shot_groups": [_group("g1", shots)], "total_duration": 80}
    report = enforce_total_duration_limit(parsed, 40.0)
    assert report["applied"] is True
    assert report["merged_shots"] == 0
    cap = 40.0 * (1 + ScriptSplitConstants.TOTAL_DURATION_TOLERANCE)
    total = sum(s["duration"] for s in parsed["shot_groups"][0]["shots"])
    assert total <= cap
    assert parsed["total_duration"] == int(round(total))
    # 等比压缩：所有镜头时长一致且低于原值
    assert all(s["duration"] == 5.0 for s in parsed["shot_groups"][0]["shots"])


def test_enforce_respects_shot_min_duration():
    # 40 个镜头 → 压缩到下限 1.5s 后仍 60s > 目标 30s 容差 → 走兜底合并
    groups = [_group(f"g{i}", [_shot(i * 4 + j + 1, 3.0) for j in range(4)]) for i in range(10)]
    parsed = {"shot_groups": groups, "total_duration": 120}
    report = enforce_total_duration_limit(parsed, 30.0)
    cap = 30.0 * (1 + ScriptSplitConstants.TOTAL_DURATION_TOLERANCE)
    total = sum(
        s["duration"] for g in parsed["shot_groups"] for s in g["shots"]
    )
    assert report["applied"] is True
    assert report["merged_shots"] > 0
    assert total <= cap
    assert all(
        s["duration"] >= ScriptSplitConstants.TOTAL_DURATION_SHOT_MIN_SECONDS
        for g in parsed["shot_groups"] for s in g["shots"]
    )
    # 合并不会产生空组
    assert all(g["shots"] for g in parsed["shot_groups"])


def test_enforce_scaling_keeps_content():
    # 压缩路径：文本/台词/在场角色全部原样保留
    a = _shot(1, 6.0, "镜头A")
    a["dialogue"] = [{"text": "你好"}]
    a["characters_present"] = ["char_001"]
    b = _shot(2, 2.0, "镜头B")
    b["dialogue"] = [{"text": "再见"}]
    b["characters_present"] = ["char_002"]
    parsed = {"shot_groups": [_group("g1", [a, b]), _group("g2", [_shot(3, 30.0)])], "total_duration": 38}
    report = enforce_total_duration_limit(parsed, 30.0)
    # 38s > 30s×1.15=34.5 → 触发等比压缩；预算充足无需合并
    assert report["applied"] is True
    assert report["merged_shots"] == 0
    flat = [s for g in parsed["shot_groups"] for s in g["shots"]]
    assert len(flat) == 3
    texts = " ".join(str(s.get("description")) for s in flat)
    assert "镜头A" in texts and "镜头B" in texts
    dialogues = [d["text"] for s in flat for d in s.get("dialogue", [])]
    assert "你好" in dialogues and "再见" in dialogues


def test_enforce_single_shot_group_cannot_merge_but_scales():
    # 每组只有 1 个镜头：无可合并对象，只能压缩（可能仍略超容差，但必须小于原始值）
    groups = [_group(f"g{i}", [_shot(i + 1, 10.0)]) for i in range(5)]
    parsed = {"shot_groups": groups, "total_duration": 50}
    report = enforce_total_duration_limit(parsed, 20.0)
    total = sum(s["duration"] for g in parsed["shot_groups"] for s in g["shots"])
    assert report["merged_shots"] == 0
    assert total < 50.0
    assert all(
        s["duration"] >= ScriptSplitConstants.TOTAL_DURATION_SHOT_MIN_SECONDS
        for g in parsed["shot_groups"] for s in g["shots"]
    )


def test_enforce_zero_target_is_noop():
    parsed = {"shot_groups": [_group("g1", [_shot(1, 5.0)])], "total_duration": 5}
    report = enforce_total_duration_limit(parsed, 0)
    assert report["applied"] is False


# ---- 倍率归一化（engine / api）----

def test_safe_duration_multiplier_clamps_and_defaults():
    from services.script_split_engine import _safe_duration_multiplier
    assert _safe_duration_multiplier({}) == 0.0
    assert _safe_duration_multiplier({"total_duration_multiplier": None}) == 0.0
    assert _safe_duration_multiplier({"total_duration_multiplier": 0}) == 0.0
    assert _safe_duration_multiplier({"total_duration_multiplier": -2}) == 0.0
    assert _safe_duration_multiplier({"total_duration_multiplier": "abc"}) == 0.0
    assert _safe_duration_multiplier({"total_duration_multiplier": 2}) == 2.0
    assert _safe_duration_multiplier({"total_duration_multiplier": "3"}) == 3.0
    assert _safe_duration_multiplier({"total_duration_multiplier": 99}) == (
        ScriptSplitConstants.TOTAL_DURATION_MULTIPLIER_MAX
    )


def test_normalize_request_config_normalizes_multiplier():
    from api.script_split import _normalize_request_config
    assert _normalize_request_config({})["total_duration_multiplier"] == 0.0
    assert _normalize_request_config({"total_duration_multiplier": "2"})["total_duration_multiplier"] == 2.0
    assert _normalize_request_config({"total_duration_multiplier": 1.5})["total_duration_multiplier"] == 1.5
    # 归一化后同语义请求的 active_key 输入稳定（字符串/数字不漂移）
    a = _normalize_request_config({"total_duration_multiplier": 2})
    b = _normalize_request_config({"total_duration_multiplier": "2.0"})
    assert a["total_duration_multiplier"] == b["total_duration_multiplier"] == 2.0
    assert _normalize_request_config({"total_duration_multiplier": 100})["total_duration_multiplier"] == (
        ScriptSplitConstants.TOTAL_DURATION_MULTIPLIER_MAX
    )
