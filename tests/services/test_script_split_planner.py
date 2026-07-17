"""Tests for script_split_planner (anchorize + plan validation).

见 docs/script/script_parser_incremental_split_design.md §20.1。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.script_split_planner import (
    anchorize_script,
    validate_segment_plan,
    plan_to_segments,
)
from config.constant import ScriptSplitConstants
from llm.script_segment_planner import build_planning_prompt


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
