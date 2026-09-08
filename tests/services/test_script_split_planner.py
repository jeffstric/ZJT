"""Tests for script_split_planner (anchorize + plan validation).

见 docs/script/script_parser_incremental_split_design.md §20.1。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.script_split_planner import (
    anchorize_script,
    validate_segment_plan,
    extract_script_title_from_excluded,
    plan_to_segments,
)
from config.constant import ScriptSplitConstants
from llm.script_segment_planner import build_exclusion_instruction, build_planning_prompt


# ---- 锚点化 ----

def test_anchorize_preserves_content_and_order():
    script = "## 场景1：主卧 - 清晨\n晨光透过窗帘。\n\n苏晚醒来。\n\n林诚熟睡。"
    blocks = anchorize_script(script)
    assert len(blocks) >= 2
    # 拼接所有 block 内容（用双换行）应等于原文（去除首尾）
    rejoined = "\n\n".join(b["content"] for b in blocks)
    assert rejoined == script
    # block_id 按序递增
    for i, b in enumerate(blocks):
        assert b["block_id"] == f"block_{i+1:04d}"


def test_anchorize_empty():
    assert anchorize_script("") == []


def test_anchorize_no_blank_lines():
    """无空行也无标记 → 整篇一个 block。"""
    script = "第一行\n第二行\n第三行"
    blocks = anchorize_script(script)
    assert len(blocks) == 1
    assert blocks[0]["content"] == "第一行\n第二行\n第三行"


def test_anchorize_scene_marker_forces_boundary():
    script = "开场内容\n## 场景2：客厅\n客厅剧情"
    blocks = anchorize_script(script)
    # 场景标记应触发分段
    assert len(blocks) >= 2


# ---- 计划校验 ----

def _make_anchors(n=4):
    return [
        {"block_id": f"block_{i+1:04d}", "start_line": i+1, "end_line": i+1,
         "content_sha256": f"h{i}", "content": f"内容{i+1}"}
        for i in range(n)
    ]


def test_valid_plan():
    anchors = _make_anchors(4)
    plan = {"schema_version": 1, "segments": [
        {"segment_id": "seg_0001", "block_ids": ["block_0001", "block_0002"]},
        {"segment_id": "seg_0002", "block_ids": ["block_0003", "block_0004"]},
    ]}
    ok, errors = validate_segment_plan(plan, anchors)
    assert ok, f"应通过，错误: {errors}"
    assert errors == []


def test_plan_missing_block():
    anchors = _make_anchors(4)
    plan = {"segments": [
        {"segment_id": "seg_0001", "block_ids": ["block_0001", "block_0002"]},
        # 漏了 block_0003, block_0004
    ]}
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    assert any(e["code"] == "block_not_covered" for e in errors)


def test_plan_duplicate_block():
    anchors = _make_anchors(4)
    plan = {"segments": [
        {"segment_id": "seg_0001", "block_ids": ["block_0001", "block_0002"]},
        {"segment_id": "seg_0002", "block_ids": ["block_0002", "block_0003", "block_0004"]},
    ]}
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    assert any(e["code"] == "block_id_duplicate" for e in errors)


def test_plan_overlap_segments():
    anchors = _make_anchors(4)
    plan = {"segments": [
        {"segment_id": "seg_0001", "block_ids": ["block_0001", "block_0003"]},
        {"segment_id": "seg_0002", "block_ids": ["block_0002", "block_0004"]},
    ]}
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    # seg_0002 的 block_0002 顺序早于 seg_0001 的 block_0003 → 重叠
    assert any(e["code"] in ("segment_overlap", "segment_block_disorder") for e in errors)


def test_plan_empty_segment():
    anchors = _make_anchors(4)
    plan = {"segments": [
        {"segment_id": "seg_0001", "block_ids": []},
        {"segment_id": "seg_0002", "block_ids": ["block_0001", "block_0002", "block_0003", "block_0004"]},
    ]}
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    assert any(e["code"] == "segment_empty" for e in errors)


def test_plan_unknown_block_id():
    anchors = _make_anchors(2)
    plan = {"segments": [
        {"segment_id": "seg_0001", "block_ids": ["block_0001", "block_9999"]},
        {"segment_id": "seg_0002", "block_ids": ["block_0002"]},
    ]}
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    assert any(e["code"] == "block_id_unknown" for e in errors)


def test_plan_ignores_legacy_estimated_shot_count():
    anchors = _make_anchors(2)
    plan = {"segments": [
        {"segment_id": "seg_0001", "block_ids": ["block_0001"], "estimated_shot_count": 0},
        {"segment_id": "seg_0002", "block_ids": ["block_0002"]},
    ]}
    ok, errors = validate_segment_plan(plan, anchors)
    assert ok
    assert errors == []


def test_planning_prompt_does_not_request_estimated_shot_count():
    prompt = build_planning_prompt(_make_anchors(2))

    assert "estimated_shot_count" not in prompt
    assert "目标镜头数" not in prompt


def test_standard_strategy_build_planning_prompt_ignores_db_locations():
    """社区版 plan 为纯分段（schema v1），不产出 location；db_locations 参数仅做签名兼容。"""
    from services.script_split_strategy import StandardScriptSplitStrategy

    strategy = StandardScriptSplitStrategy()
    anchors = _make_anchors(2)
    # 旧签名仍可用
    assert strategy.build_planning_prompt(anchors, 65536) is None
    # 新签名（带 db_locations）向后兼容，社区版不构造 location prompt
    assert strategy.build_planning_prompt(
        anchors, 65536, db_locations=[{"id": 1, "name": "露台"}]
    ) is None


def test_plan_duplicate_segment_id():
    anchors = _make_anchors(2)
    plan = {"segments": [
        {"segment_id": "seg_0001", "block_ids": ["block_0001"]},
        {"segment_id": "seg_0001", "block_ids": ["block_0002"]},
    ]}
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    assert any(e["code"] == "segment_id_duplicate" for e in errors)


# ---- excluded_block_ids（非正文 block 排除）----

def _make_script_anchors():
    """模拟剧本头部元信息 + 正文的锚点结构。"""
    return [
        {"block_id": "block_0001", "start_line": 1, "end_line": 1,
         "content_sha256": "h1", "content": "# 第1集：《新来的保安有点怪》"},
        {"block_id": "block_0002", "start_line": 3, "end_line": 3,
         "content_sha256": "h2", "content": "## 核心爽点：商业洞察力降维打击"},
        {"block_id": "block_0003", "start_line": 5, "end_line": 5,
         "content_sha256": "h3", "content": "---"},
        {"block_id": "block_0004", "start_line": 7, "end_line": 8,
         "content_sha256": "h4", "content": "[场景 凌云大厦大厅 清晨]\n场景编号：A1"},
        {"block_id": "block_0005", "start_line": 10, "end_line": 10,
         "content_sha256": "h5", "content": "赵志高（叉着腰，大声呵斥）：李保国！你看看你扫的什么地！"},
    ]


def test_plan_with_excluded_header_blocks_ok():
    """头部标题/爽点/分隔线被排除，segments 覆盖正文 → 通过。"""
    anchors = _make_script_anchors()
    plan = {
        "schema_version": 1,
        "excluded_block_ids": ["block_0001", "block_0002", "block_0003"],
        "segments": [
            {"segment_id": "seg_0001", "block_ids": ["block_0004", "block_0005"]},
        ],
    }
    ok, errors = validate_segment_plan(plan, anchors)
    assert ok, f"应通过，错误: {errors}"
    assert errors == []


def test_plan_without_excluded_field_keeps_legacy_behavior():
    """旧模型输出无 excluded_block_ids 字段 → 行为与历史一致（必须全覆盖）。"""
    anchors = _make_script_anchors()
    plan = {"segments": [
        {"segment_id": "seg_0001", "block_ids": ["block_0004", "block_0005"]},
    ]}
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    assert any(e["code"] == "block_not_covered" for e in errors)


def test_plan_excluded_unknown_block_id():
    anchors = _make_anchors(2)
    plan = {
        "excluded_block_ids": ["block_9999"],
        "segments": [
            {"segment_id": "seg_0001", "block_ids": ["block_0001", "block_0002"]},
        ],
    }
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    assert any(e["code"] == "block_id_unknown" for e in errors)


def test_plan_excluded_invalid_type():
    anchors = _make_anchors(2)
    plan = {
        "excluded_block_ids": "block_0001",
        "segments": [
            {"segment_id": "seg_0001", "block_ids": ["block_0001", "block_0002"]},
        ],
    }
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    assert any(e["code"] == "excluded_block_ids_invalid" for e in errors)


def test_plan_excluded_same_block_twice():
    anchors = _make_script_anchors()
    plan = {
        "excluded_block_ids": ["block_0001", "block_0001"],
        "segments": [
            {"segment_id": "seg_0001", "block_ids": ["block_0002", "block_0003",
                                                     "block_0004", "block_0005"]},
        ],
    }
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    assert any(e["code"] == "block_id_duplicate" for e in errors)


def test_plan_excluded_conflicts_with_segment():
    """同一 block 同时出现在 excluded 与 segment → 报重复。"""
    anchors = _make_script_anchors()
    plan = {
        "excluded_block_ids": ["block_0001"],
        "segments": [
            {"segment_id": "seg_0001", "block_ids": ["block_0001", "block_0002",
                                                     "block_0003", "block_0004",
                                                     "block_0005"]},
        ],
    }
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    assert any(e["code"] == "block_id_duplicate" for e in errors)


def test_plan_excluded_all_blocks_leaves_no_segments():
    """全部 block 被排除 → segments 为空，现有 plan_no_segments 拦截。"""
    anchors = _make_anchors(2)
    plan = {
        "excluded_block_ids": ["block_0001", "block_0002"],
        "segments": [],
    }
    ok, errors = validate_segment_plan(plan, anchors)
    assert not ok
    assert any(e["code"] == "plan_no_segments" for e in errors)


def test_extract_script_title_from_excluded():
    anchors = _make_script_anchors()
    title = extract_script_title_from_excluded(anchors[:3])
    assert title == "第1集：《新来的保安有点怪》"


def test_extract_script_title_prefers_first_heading():
    blocks = [
        {"block_id": "block_0001", "content": "---"},
        {"block_id": "block_0002", "content": "## 核心爽点：降维打击"},
        {"block_id": "block_0003", "content": "# 第2集"},
    ]
    assert extract_script_title_from_excluded(blocks) == "核心爽点：降维打击"


def test_extract_script_title_empty_when_no_heading():
    assert extract_script_title_from_excluded(
        [{"block_id": "block_0001", "content": "---"}]
    ) == ""
    assert extract_script_title_from_excluded([]) == ""
    assert extract_script_title_from_excluded(None) == ""


def test_planning_prompt_contains_exclusion_instruction():
    prompt = build_planning_prompt(_make_script_anchors())
    assert "excluded_block_ids" in prompt
    # 正文类内容明确禁止排除
    assert "[场景" in prompt
    assert "场景编号" in prompt
    # 输出格式示例包含新字段
    assert '"excluded_block_ids": []' in prompt


def test_exclusion_instruction_is_self_contained():
    """共享指引可独立注入 enterprise 自定义提示词（prompt_override 路径）。"""
    instruction = build_exclusion_instruction()
    assert "excluded_block_ids" in instruction
    assert "不得排除" in instruction


# ---- plan_to_segments ----

def test_plan_to_segments():
    anchors = _make_anchors(4)
    plan = {"segments": [
        {"segment_id": "seg_A", "block_ids": ["block_0001", "block_0002"]},
        {"segment_id": "seg_B", "block_ids": ["block_0003", "block_0004"]},
    ]}
    segs = plan_to_segments(plan, anchors)
    assert len(segs) == 2
    assert segs[0]["segment_index"] == 1
    assert segs[0]["segment_id"] == "seg_A"
    assert "内容1" in segs[0]["source_content"]
    assert "内容3" in segs[1]["source_content"]


def test_plan_to_segments_keeps_llm_boundary_when_under_hard_limit():
    anchors = _make_anchors(2)
    plan = {"segments": [
        {"segment_id": "seg_A", "block_ids": ["block_0001", "block_0002"]},
    ]}

    segs = plan_to_segments(plan, anchors)

    assert len(segs) == 1
    assert segs[0]["segment_id"] == "seg_A"


def test_plan_to_segments_splits_oversized_multi_block_range_at_block_boundary():
    anchors = [
        {"block_id": "block_0001", "content": "甲" * 800},
        {"block_id": "block_0002", "content": "乙" * 800},
    ]
    plan = {"segments": [
        {"segment_id": "seg_A", "block_ids": ["block_0001", "block_0002"]},
    ]}

    segs = plan_to_segments(plan, anchors)

    assert len(segs) == 2
    assert [seg["source_block_ids"] for seg in segs] == [
        ["block_0001"],
        ["block_0002"],
    ]
    assert all(
        len(seg["source_content"]) <= ScriptSplitConstants.SEGMENT_MAX_SOURCE_CHARS
        for seg in segs
    )
    assert "\n\n".join(seg["source_content"] for seg in segs) == "甲" * 800 + "\n\n" + "乙" * 800


def test_plan_to_segments_splits_single_oversized_block_without_losing_text():
    source = "甲说完一句话。" * 220
    anchors = [{"block_id": "block_0001", "content": source}]
    plan = {"segments": [
        {"segment_id": "seg_A", "block_ids": ["block_0001"]},
    ]}

    segs = plan_to_segments(plan, anchors)

    assert len(segs) > 1
    assert all(
        len(seg["source_content"]) <= ScriptSplitConstants.SEGMENT_MAX_SOURCE_CHARS
        for seg in segs
    )
    assert "".join(seg["source_content"] for seg in segs) == source
