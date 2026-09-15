"""总分镜时长控制单元测试。

覆盖 docs/script/script_split_total_duration_control.md 的核心函数：
- estimate_script_duration_seconds：整篇基准时长估算（旧口径，兜底回退用）
- estimate_script_dialogue_seconds / extract_script_dialogue_text：启发式台词过滤
- compute_shot_dialogue_seconds / apply_dialogue_matched_shot_durations：逐镜台词锚定
- compute_total_duration_target_seconds：总时长目标的三级口径回退
- compute_segment_duration_budget_seconds：段级预算分解（台词锚定）
- enforce_total_duration_limit：合并后确定性归一化（压缩/兜底合并/台词下限）

以及 _safe_duration_multiplier（engine）与 _normalize_request_config（api）
的倍率归一化。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constant import ScriptSplitConstants
from llm.script_parser import (
    apply_dialogue_matched_shot_durations,
    compute_segment_content_seconds,
    compute_segment_declared_budget_seconds,
    compute_segment_duration_budget_seconds,
    compute_shot_dialogue_seconds,
    compute_total_duration_target_seconds,
    enforce_total_duration_limit,
    estimate_script_dialogue_seconds,
    estimate_script_duration_seconds,
    extract_script_declared_duration_seconds,
    extract_script_dialogue_text,
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
    # 台词锚定口径：显式传入段台词字数（来自阶段一规划 dialogue_text）时，
    # 各段预算之和 ≈ 倍率 × 台词总时长 ÷ 对白占比
    script = "他走进房间看了看四周" * 100  # 1000 个纯 CJK 字，混合速率=4.5
    multiplier = 2.0
    budget_a = compute_segment_duration_budget_seconds(script, "段一原文", multiplier, dialogue_chars=45)
    budget_b = compute_segment_duration_budget_seconds(script, "段二原文", multiplier, dialogue_chars=90)
    target = multiplier * (135 / 4.5) / ScriptSplitConstants.TOTAL_DURATION_DIALOGUE_SHARE
    # 段台词字数拼接=全剧本台词 → 预算和应贴近目标（5% 内）
    assert abs((budget_a + budget_b) - target) / target < 0.05


def test_segment_budget_floor_and_zero_multiplier():
    script = "他走进房间看了看四周。" * 10
    assert compute_segment_duration_budget_seconds(script, "三个字", 2.0) == (
        ScriptSplitConstants.TOTAL_DURATION_SEGMENT_BUDGET_MIN_SECONDS
    )
    assert compute_segment_duration_budget_seconds(script, script, 0) == 0.0
    assert compute_segment_duration_budget_seconds(script, "", 2.0) == 0.0


def test_segment_budget_empty_dialogue_falls_back_to_legacy_formula():
    # 规划明确该段无台词（dialogue_chars=0）→ 旧公式（倍率 × 段字符数 ÷ 速率）
    script = "他走进房间看了看四周" * 100  # 纯 CJK，速率 4.5
    segment = "他走进房间看了看四周" * 10  # 100 字
    budget = compute_segment_duration_budget_seconds(script, segment, 2.0, dialogue_chars=0)
    assert budget == round(2.0 * 100 / 4.5, 1)


def test_segment_budget_heuristic_when_dialogue_chars_missing():
    # dialogue_chars 缺省（规划未输出该字段）→ 启发式过滤：标记/括号行剔除，
    # 只数台词，再 ÷ 对白占比
    script = "他走进房间看了看四周" * 100  # 纯 CJK，速率 4.5
    segment = "\n".join(["[场景 客厅 夜]", "（他走进房间。）", "林深：" + "你" * 45])
    budget = compute_segment_duration_budget_seconds(script, segment, 1.0)
    assert budget == round(45 / 4.5 / ScriptSplitConstants.TOTAL_DURATION_DIALOGUE_SHARE, 1)


# ---- extract_script_dialogue_text / estimate_script_dialogue_seconds ----

def test_extract_dialogue_skips_markers_headers_and_stage_directions():
    text = "\n".join([
        "# 第 1 集：标题",             # # 开头跳过
        "[场景 客厅 夜]",              # [ 开头跳过
        "【第一幕】",                  # 【 开头跳过
        "场景编号：A1",                # 场景编号开头跳过
        "时间：夜晚",                  # 头部关键词 + 冒号跳过
        "地点：客厅",
        "BGM：轻音乐",
        "音效：雨声",
        "（他走进房间，环顾四周。）",   # 整行括号包裹跳过
        "林深：你藏了什么。",
    ])
    assert extract_script_dialogue_text(text) == "你藏了什么。"


def test_extract_dialogue_counts_text_after_first_colon():
    assert extract_script_dialogue_text("林深（低声）：让我看看，你藏了什么") == "让我看看，你藏了什么"
    # 英文冒号同样识别；首个冒号后的内容全部计入
    assert extract_script_dialogue_text("林深: 你好: 再见") == "你好: 再见"


def test_extract_dialogue_quoted_text_only_for_plain_lines():
    # 无冒号非括号行：只数成对引号内的文字
    assert extract_script_dialogue_text("他说“你好”就走了") == "你好"
    assert extract_script_dialogue_text('他说"你好"就走了') == "你好"
    assert extract_script_dialogue_text("他说「你好」就走了") == "你好"
    assert extract_script_dialogue_text("他说『你好』就走了") == "你好"
    # 该行无引号则整行计入（旁白）
    assert extract_script_dialogue_text("他走进房间看了看四周") == "他走进房间看了看四周"


def test_dialogue_estimate_proportional_to_dialogue_chars():
    text = "林深：" + "你" * 90  # 90 个 CJK 台词字 ÷ 4.5 = 20s
    assert estimate_script_dialogue_seconds(text) == 20.0


def test_dialogue_estimate_falls_back_when_no_dialogue_matched():
    # 整篇零匹配（全是标记/括号/头部行）→ 回退整篇估算
    text = "\n".join(["[场景 客厅 夜]", "（他走进房间。）", "时间：夜晚"])
    assert estimate_script_dialogue_seconds(text) == estimate_script_duration_seconds(text)


# ---- compute_shot_dialogue_seconds ----

def test_shot_dialogue_seconds_sums_all_characters():
    shot = {"dialogue": [
        {"character_id": "c1", "character_name": "甲", "text": "你好吗"},
        {"character_id": "c2", "character_name": "乙", "text": "我很好"},
    ]}
    assert abs(compute_shot_dialogue_seconds(shot) - 6 / 4.5) < 0.01


def test_shot_dialogue_seconds_empty_and_malformed():
    assert compute_shot_dialogue_seconds({}) == 0.0
    assert compute_shot_dialogue_seconds({"dialogue": []}) == 0.0
    assert compute_shot_dialogue_seconds({"dialogue": None}) == 0.0
    assert compute_shot_dialogue_seconds({"dialogue": "不是列表"}) == 0.0
    assert compute_shot_dialogue_seconds({"dialogue": [{"text": ""}, {"text": "  "}, {}]}) == 0.0


# ---- apply_dialogue_matched_shot_durations ----

def test_apply_dialogue_matched_overwrites_dialogue_shots_only():
    shots = [
        {**_shot(1, 3.0), "dialogue": [{"text": "你" * 45}]},  # 45 字 → 锚定 10s
        {**_shot(2, 6.0), "dialogue": [{"text": "好"}]},        # 1 字 → 下限 2s
        _shot(3, 7.5),                                          # 无对白不动
    ]
    parsed = {"shot_groups": [_group("g1", shots)]}
    matched = apply_dialogue_matched_shot_durations(parsed)
    assert matched == 2
    assert shots[0]["duration"] == 10.0
    assert shots[1]["duration"] == ScriptSplitConstants.SCRIPT_DURATION_DIALOGUE_SHOT_MIN_SECONDS
    assert shots[2]["duration"] == 7.5


def test_apply_dialogue_matched_sums_multi_character_dialogue():
    shots = [
        {**_shot(1, 2.0), "dialogue": [
            {"character_id": "c1", "text": "你" * 22},
            {"character_id": "c2", "text": "好" * 23},
        ]},  # 合计 45 字 → 10s
    ]
    parsed = {"shot_groups": [_group("g1", shots)]}
    assert apply_dialogue_matched_shot_durations(parsed) == 1
    assert shots[0]["duration"] == 10.0


# ---- compute_total_duration_target_seconds ----

def test_total_target_prefers_shot_dialogue_seconds():
    # 结构化对白总时长 > 0 → 倍率 × 台词总时长 ÷ 对白占比
    target, source = compute_total_duration_target_seconds("任何剧本", 74.0, 1.0)
    assert source == "shots"
    assert target == round(74.0 / ScriptSplitConstants.TOTAL_DURATION_DIALOGUE_SHARE, 1)


def test_total_target_heuristic_fallback():
    # 无结构化对白但启发式能提取台词 → 倍率 × 启发式台词时长 ÷ 对白占比
    script = "林深：" + "你" * 45
    target, source = compute_total_duration_target_seconds(script, 0.0, 2.0)
    assert source == "heuristic"
    assert target == round(2.0 * (45 / 4.5) / ScriptSplitConstants.TOTAL_DURATION_DIALOGUE_SHARE, 1)


def test_total_target_full_text_fallback():
    # 启发式也匹配不到台词 → 旧口径（倍率 × 整篇基准时长）
    script = "（他走进房间。）\n[场景 客厅]"
    target, source = compute_total_duration_target_seconds(script, 0.0, 2.0)
    assert source == "full_text"
    assert target == round(estimate_script_duration_seconds(script) * 2.0, 1)


# ---- extract_script_declared_duration_seconds（剧本自述标注总时长）----

def test_declared_duration_from_title_parentheses():
    assert extract_script_declared_duration_seconds("# 第1集：《贱婢》（30秒）\n正文……") == 30.0
    assert extract_script_declared_duration_seconds("第1集 (1.5分钟)") == 90.0


def test_declared_duration_keyword_variants():
    assert extract_script_declared_duration_seconds("时长：30秒") == 30.0
    assert extract_script_declared_duration_seconds("总时长： 90s") == 90.0
    assert extract_script_declared_duration_seconds("预计1分钟") == 60.0
    assert extract_script_declared_duration_seconds("片长： 2 min") == 120.0
    assert extract_script_declared_duration_seconds("预计时长：1.5分钟") == 90.0
    assert extract_script_declared_duration_seconds("成片时长：45秒") == 45.0


def test_declared_duration_ignores_body_time_descriptions():
    # 正文/台词里的时间描述没有关键词引导、也不是纯括号标注 → 不误判
    assert extract_script_declared_duration_seconds("他等了30秒，终于开口。") is None
    assert extract_script_declared_duration_seconds("（他等了30秒。）") is None
    assert extract_script_declared_duration_seconds("林深：再等1分钟就走。") is None
    assert extract_script_declared_duration_seconds("") is None
    assert extract_script_declared_duration_seconds(None) is None


def test_declared_duration_sanity_window():
    # 超出有效区间的标注视为误识别
    assert extract_script_declared_duration_seconds("时长：2秒") is None
    assert extract_script_declared_duration_seconds("时长：400分钟") is None
    # 第一个标注无效时取下一处有效标注
    text = "时长：2秒\n总时长：60秒"
    assert extract_script_declared_duration_seconds(text) == 60.0


def test_declared_duration_first_match_wins():
    # 两处都有效时按文本位置取第一个
    assert extract_script_declared_duration_seconds("（45秒）\n时长：60秒") == 45.0
    assert extract_script_declared_duration_seconds("时长：60秒\n（45秒）") == 60.0


def test_total_target_declared_overrides_shots():
    # 标注总时长优先级最高：倍率 × 标注秒数（不除以对白占比）
    target, source = compute_total_duration_target_seconds(
        "任何剧本", 74.0, 2.0, declared_duration_seconds=30.0)
    assert source == "declared"
    assert target == 60.0


# ---- 标注口径段预算分摊 ----

def test_segment_content_seconds_units():
    script = "他走进房间看了看四周" * 100  # 纯 CJK，速率 4.5
    # 台词 45 字 → 45/4.5/0.6 ≈ 16.67（1 倍口径，不含倍率与段下限）
    assert abs(compute_segment_content_seconds(script, "x", 45) - 45 / 4.5 / 0.6) < 0.01
    # 无台词段 → 段字符数 ÷ 速率（旧口径 1 倍值）
    assert abs(compute_segment_content_seconds(script, "他" * 90, 0) - 90 / 4.5) < 0.01
    # 空段 → 0
    assert compute_segment_content_seconds(script, "", None) == 0.0


def test_segment_declared_budget_allocates_by_content_share():
    # 标注口径：各段预算按内容量占比分摊，预算之和 ≈ 倍率 × 标注秒数
    budget_a = compute_segment_declared_budget_seconds(60.0, 1.0, 10.0, 40.0)
    budget_b = compute_segment_declared_budget_seconds(60.0, 1.0, 30.0, 40.0)
    assert budget_a == 15.0
    assert budget_b == 45.0
    assert abs(budget_a + budget_b - 60.0) < 0.2


def test_segment_declared_budget_floor_and_empty():
    floor = ScriptSplitConstants.TOTAL_DURATION_SEGMENT_BUDGET_MIN_SECONDS
    # 极小占比段托底到段下限
    assert compute_segment_declared_budget_seconds(60.0, 1.0, 0.1, 100.0) == floor
    # 空段 / 零总量 / 零倍率 → 0
    assert compute_segment_declared_budget_seconds(60.0, 1.0, 0.0, 100.0) == 0.0
    assert compute_segment_declared_budget_seconds(60.0, 1.0, 10.0, 0.0) == 0.0
    assert compute_segment_declared_budget_seconds(60.0, 0, 10.0, 100.0) == 0.0


def test_plan_prompt_and_validation_tolerate_declared_duration():
    # 规划 prompt 要求输出 declared_duration_seconds；plan 校验容忍该顶层字段
    from llm.script_segment_planner import build_planning_prompt
    from services.script_split_planner import validate_segment_plan
    anchors = [{"block_id": "block_0001", "start_line": 1, "end_line": 1,
                "content_sha256": "x", "content": "内容"}]
    prompt = build_planning_prompt(anchors)
    assert "declared_duration_seconds" in prompt
    plan = {
        "schema_version": 1,
        "declared_duration_seconds": 30,
        "segments": [{"segment_id": "seg_0001", "block_ids": ["block_0001"]}],
    }
    ok, errors = validate_segment_plan(plan, anchors)
    assert ok, errors


def test_plan_declared_duration_seconds_lookup():
    from services.script_split_engine import _plan_declared_duration_seconds
    # 规划提炼值优先
    assert _plan_declared_duration_seconds({"declared_duration_seconds": 30}, "剧本") == 30.0
    # plan 值超出 sanity 区间视为无效，回退正则
    assert _plan_declared_duration_seconds({"declared_duration_seconds": 2}, "时长：60秒") == 60.0
    # 字段缺失回退正则
    assert _plan_declared_duration_seconds({}, "# 第1集（30秒）") == 30.0
    assert _plan_declared_duration_seconds({"declared_duration_seconds": None}, "片长：1分钟") == 60.0
    # 均无 → None
    assert _plan_declared_duration_seconds({}, "他等了30秒") is None
    assert _plan_declared_duration_seconds({"declared_duration_seconds": "abc"}, "无标注剧本") is None


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


def test_enforce_compress_respects_dialogue_floor():
    # 压缩路径：有对白镜头的下限 = 台词朗读时长（不穿透），其余镜头按旧下限
    parsed = {
        "shot_groups": [
            _group("g1", [{**_shot(1, 20.0), "dialogue": [{"text": "你" * 45}]}]),  # 台词 10s
            _group("g2", [_shot(2, 40.0)]),
        ],
        "total_duration": 60,
    }
    report = enforce_total_duration_limit(parsed, 20.0)
    assert report["direction"] == "compress"
    durations = {
        s["shot_number"]: s["duration"]
        for g in parsed["shot_groups"] for s in g["shots"]
    }
    # scale=20/60≈0.333：shot1 20×1/3≈6.7 被台词下限 10s 托住；shot2 40×1/3≈13.3
    assert durations[1] == 10.0
    assert durations[2] == 13.3
    assert "dialogue_floor_exceeded_seconds" not in report


def test_enforce_reports_dialogue_floor_exceeded():
    # 每组仅 1 个镜头（无可合并对象）且台词下限总和超过目标上限：
    # 接受超出并上报差额（台词必须念完，不再继续压）
    parsed = {
        "shot_groups": [
            _group("g1", [{**_shot(1, 30.0), "dialogue": [{"text": "甲" * 90}]}]),
            _group("g2", [{**_shot(2, 30.0), "dialogue": [{"text": "乙" * 90}]}]),
            _group("g3", [{**_shot(3, 30.0), "dialogue": [{"text": "丙" * 90}]}]),
        ],
        "total_duration": 90,
    }
    report = enforce_total_duration_limit(parsed, 20.0)
    cap = 20.0 * (1 + ScriptSplitConstants.TOTAL_DURATION_TOLERANCE)
    # 每镜头压到台词下限 20s，总时长 60s 仍超上限 23s
    total = sum(s["duration"] for g in parsed["shot_groups"] for s in g["shots"])
    assert total == 60.0
    assert report["merged_shots"] == 0
    assert report["dialogue_floor_exceeded_seconds"] == round(total - cap, 1)


# ---- engine 段台词字数查找（_segment_plan_dialogue_chars）----

def test_segment_plan_dialogue_chars_lookup():
    from services.script_split_engine import _segment_plan_dialogue_chars
    plan = {"segments": [
        {"segment_id": "seg_0001", "block_ids": ["block_0001"], "dialogue_text": "你" * 45},
        {"segment_id": "seg_0002", "block_ids": ["block_0002"], "dialogue_text": ""},
        {"segment_id": "seg_0003", "block_ids": ["block_0003"]},  # 未输出该字段
    ]}
    seg1 = SimpleNamespace(segment_id="seg_0001", source_content="内容")
    assert _segment_plan_dialogue_chars(plan, seg1, "剧本") == 45
    # 明确空台词 → 0（调用方回退旧公式）
    assert _segment_plan_dialogue_chars(
        plan, SimpleNamespace(segment_id="seg_0002", source_content="x"), "剧本") == 0
    # 字段缺失 → None（调用方走启发式）
    assert _segment_plan_dialogue_chars(
        plan, SimpleNamespace(segment_id="seg_0003", source_content="x"), "剧本") is None
    # 段不在规划中 → None
    assert _segment_plan_dialogue_chars(
        plan, SimpleNamespace(segment_id="seg_9999", source_content="x"), "剧本") is None
    assert _segment_plan_dialogue_chars({}, seg1, "剧本") is None


def test_segment_plan_dialogue_chars_part_split_prorated():
    # 基段被 SEGMENT_MAX_SOURCE_CHARS 切成多个 part 时按原文字符比例分摊台词字数
    from services.script_split_engine import _segment_plan_dialogue_chars
    script = "甲" * 100 + "\n\n" + "乙" * 300  # block_0001=100 字，block_0002=300 字
    plan = {"segments": [
        {"segment_id": "seg_0001", "block_ids": ["block_0001", "block_0002"],
         "dialogue_text": "你" * 100},
    ]}
    seg = SimpleNamespace(segment_id="seg_0001_part_01", source_content="甲" * 100)
    # part 占基段 100/400 → 25 字
    assert _segment_plan_dialogue_chars(plan, seg, script) == 25


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
