"""剧本分段拆分 - 规划/注册表/策略纯函数单元测试。

覆盖测试方案 §2.2：
- anchorize_script 稳定锚点
- validate_segment_plan 覆盖/顺序/连续性校验
- plan_to_segments 切分
- AcceptedRegistry 实体 ID 复用
- validate_segment_entities / validate_segment_spatial_references
- renumber_global 镜号重排
- StandardScriptSplitStrategy / get_script_split_strategy 门面

这些纯函数不连库、不调 LLM，直接断言业务逻辑。
"""
import pytest

from services.script_split_planner import (
    anchorize_script,
    plan_to_segments,
    validate_segment_plan,
)
from services.script_split_registry import (
    AcceptedRegistry,
    renumber_global,
    validate_segment_entities,
    validate_segment_spatial_references,
)
from services.script_split_strategy import (
    StandardScriptSplitStrategy,
    get_script_split_strategy,
)
from services.storyboard_spatial.exceptions import (
    StoryboardEnterpriseFeatureRequired,
)


# ---------------- anchorize_script ----------------

class TestAnchorizeScript:
    def test_deterministic_block_ids(self):
        """同一剧本两次调用，block_id 序列完全一致（确定性）。"""
        script = "场景一：清晨。\n\n场景二：黄昏。"
        a1 = anchorize_script(script)
        a2 = anchorize_script(script)
        assert [b["block_id"] for b in a1] == [b["block_id"] for b in a2]
        assert a1[0]["block_id"] == "block_0001"

    def test_empty_script_returns_empty(self):
        assert anchorize_script("") == []
        assert anchorize_script(None) == []  # type: ignore[arg-type]

    def test_each_block_has_sha_and_content(self):
        anchors = anchorize_script("第一段。\n\n第二段。")
        assert len(anchors) == 2
        for b in anchors:
            assert b["content"]
            assert len(b["content_sha256"]) == 64
            assert b["start_line"] <= b["end_line"]

    def test_does_not_mutate_original_content(self):
        """锚点化不改变每段原文内容（逐 block 比对）。"""
        script = "甲。\n\n乙。\n\n丙。"
        anchors = anchorize_script(script)
        assert [b["content"] for b in anchors] == ["甲。", "乙。", "丙。"]


# ---------------- validate_segment_plan ----------------

class TestValidateSegmentPlan:
    @staticmethod
    def _anchors(n=3):
        return anchorize_script("\n\n".join(f"第 {i} 段内容。" for i in range(1, n + 1)))

    def test_valid_plan_passes(self):
        anchors = self._anchors()
        block_ids = [b["block_id"] for b in anchors]
        plan = {"segments": [
            {"segment_id": "seg_1", "block_ids": [block_ids[0]]},
            {"segment_id": "seg_2", "block_ids": block_ids[1:]},
        ]}
        ok, errors = validate_segment_plan(plan, anchors)
        assert ok, errors
        assert errors == []

    def test_missing_block_coverage_fails(self):
        """plan 的 block 并集 ≠ 原文全部 block → 报缺失。"""
        anchors = self._anchors(3)
        bid0 = anchors[0]["block_id"]
        plan = {"segments": [{"segment_id": "seg_1", "block_ids": [bid0]}]}
        ok, errors = validate_segment_plan(plan, anchors)
        assert not ok
        codes = [e["code"] for e in errors]
        assert "block_not_covered" in codes

    def test_duplicate_block_across_segments_fails(self):
        """同一 block 被多段重复包含 → 报错。"""
        anchors = self._anchors(3)
        bid0 = anchors[0]["block_id"]
        bid1 = anchors[1]["block_id"]
        bid2 = anchors[2]["block_id"]
        plan = {"segments": [
            {"segment_id": "seg_1", "block_ids": [bid0, bid1]},
            {"segment_id": "seg_2", "block_ids": [bid1, bid2]},  # bid1 重复
        ]}
        ok, errors = validate_segment_plan(plan, anchors)
        assert not ok
        assert any(e["code"] == "block_id_duplicate" for e in errors)

    def test_segment_overlap_order_fails(self):
        """跨段顺序：本段最小序号必须 > 上一段最大序号。"""
        anchors = self._anchors(3)
        b0, b1, b2 = (a["block_id"] for a in anchors)
        plan = {"segments": [
            {"segment_id": "seg_1", "block_ids": [b0, b2]},  # 跨到 b2
            {"segment_id": "seg_2", "block_ids": [b1]},       # b1 序号 < b2 → 重叠
        ]}
        ok, errors = validate_segment_plan(plan, anchors)
        assert not ok
        assert any(e["code"] == "segment_overlap" for e in errors)

    def test_empty_segment_rejected(self):
        anchors = self._anchors()
        b0 = anchors[0]["block_id"]
        plan = {"segments": [
            {"segment_id": "seg_1", "block_ids": []},  # 空
            {"segment_id": "seg_2", "block_ids": [b0]},
        ]}
        ok, errors = validate_segment_plan(plan, anchors)
        assert not ok
        assert any(e["code"] == "segment_empty" for e in errors)

    def test_non_dict_plan_rejected(self):
        ok, errors = validate_segment_plan([], self._anchors())  # type: ignore[arg-type]
        assert not ok and errors[0]["code"] == "plan_not_dict"


# ---------------- plan_to_segments ----------------

class TestPlanToSegments:
    def test_segments_contain_source_content(self):
        anchors = anchorize_script("第一段。\n\n第二段。")
        b0, b1 = anchors[0]["block_id"], anchors[1]["block_id"]
        plan = {"segments": [
            {"segment_id": "seg_1", "block_ids": [b0]},
            {"segment_id": "seg_2", "block_ids": [b1]},
        ]}
        segs = plan_to_segments(plan, anchors)
        assert len(segs) == 2
        assert segs[0]["segment_id"] == "seg_1"
        assert segs[0]["source_content"] == "第一段。"
        assert len(segs[0]["source_sha256"]) == 64


# ---------------- AcceptedRegistry ----------------

class TestAcceptedRegistry:
    def test_commit_and_find_by_name(self):
        reg = AcceptedRegistry()
        reg.commit_entity("character", "char_001", {"name": "小明", "character_db_id": 10})
        assert reg.find_by_name("character", "小明") == "char_001"
        assert reg.find_by_db_id("character", 10) == "char_001"

    def test_find_by_name_normalizes(self):
        """名称查找走规范化（大小写/空白）。"""
        reg = AcceptedRegistry()
        reg.commit_entity("character", "char_001", {"name": "Alice"})
        assert reg.find_by_name("character", "  alice ") == "char_001"

    def test_id_reservations_advances_cursor(self):
        reg = AcceptedRegistry()
        assert reg.id_reservations()["character_start"] == "char_001"
        reg.commit_entity("character", "char_001", {"name": "甲"})
        # 游标推进到下一个
        assert reg.id_reservations()["character_start"] == "char_002"

    def test_to_context_snapshot(self):
        reg = AcceptedRegistry()
        reg.commit_entity("location", "loc_001", {"title": "客厅"})
        ctx = reg.to_context()
        assert len(ctx["locations"]) == 1
        assert ctx["locations"][0]["title"] == "客厅"


# ---------------- validate_segment_entities ----------------

class TestValidateSegmentEntities:
    def test_reuse_existing_id_passes(self):
        """同 db_id 必须复用已有全局 ID。"""
        reg = AcceptedRegistry()
        reg.commit_entity("character", "char_001", {"name": "小明", "character_db_id": 5})
        seg_result = {"characters": [{"id": "char_001", "name": "小明", "character_db_id": 5}]}
        ok, errors = validate_segment_entities(seg_result, reg)
        assert ok, errors

    def test_new_entity_below_reservation_rejected(self):
        """新实体 id 序号低于预留起始 → 拒绝（可能复用了已占用编号）。

        AcceptedRegistry 初始预留 character_start=char_001；若先 commit 了 char_001，
        游标推进到 char_002，此时新实体若给 char_001 即低于预留起始。
        """
        reg = AcceptedRegistry()
        reg.commit_entity("character", "char_001", {"name": "小明"})
        # 游标已推进到 char_002，新实体给 char_001（低于预留起始）应拒绝
        seg_result = {"characters": [{"id": "char_001", "name": "陌生人"}]}
        ok, errors = validate_segment_entities(seg_result, reg)
        assert not ok
        assert any(e["code"] == "character_id_not_reserved" for e in errors)

    def test_existing_entity_wrong_id_rejected(self):
        """已登记实体（同名）必须复用原 ID，换 ID → 拒绝。"""
        reg = AcceptedRegistry()
        reg.commit_entity("character", "char_001", {"name": "小明"})
        seg_result = {"characters": [{"id": "char_002", "name": "小明"}]}
        ok, errors = validate_segment_entities(seg_result, reg)
        assert not ok
        assert any(e["code"] == "character_id_should_reuse" for e in errors)

    def test_new_entity_at_reservation_passes(self):
        """新实体使用合法预留起始 id（序号 >= 预留起始）→ 通过。"""
        reg = AcceptedRegistry()
        seg_result = {"characters": [{"id": "char_001", "name": "全新角色"}]}
        ok, errors = validate_segment_entities(seg_result, reg)
        assert ok, errors


# ---------------- validate_segment_spatial_references ----------------

class TestValidateSegmentSpatialReferences:
    def test_valid_registry_reference_passes(self):
        """shot 的 spatial_layout.space_unit_refs 引用 registry 已登记的 su → 通过。"""
        reg = AcceptedRegistry()
        reg.commit_spatial_world({"space_units": [
            {"space_unit_id": "su_1", "anchors": [], "coordinate_frame": {}}
        ]})
        seg_result = {"shot_groups": [{"shots": [
            {"shot_id": "s1", "spatial_layout": {"space_unit_refs": ["su_1"]}}
        ]}]}
        ok, errors = validate_segment_spatial_references(seg_result, reg)
        assert ok, errors

    def test_dangling_space_unit_ref_rejected(self):
        """shot 的 space_unit_refs 引用不存在的 su → 拒绝。"""
        reg = AcceptedRegistry()
        seg_result = {"shot_groups": [{"shots": [
            {"shot_id": "s1", "spatial_layout": {"space_unit_refs": ["ghost_su"]}}
        ]}]}
        ok, errors = validate_segment_spatial_references(seg_result, reg)
        assert not ok
        assert any(e["code"] == "ref_space_unit_unknown" for e in errors)

    def test_dangling_character_ref_rejected(self):
        """camera_anchor.relative_to_character.character_id 引用未登记角色 → 拒绝。"""
        reg = AcceptedRegistry()
        seg_result = {"shot_groups": [{"shots": [
            {"shot_id": "s1", "spatial_layout": {
                "camera_anchor": {"relative_to_character": {"character_id": "ghost_char"}}
            }}
        ]}]}
        ok, errors = validate_segment_spatial_references(seg_result, reg)
        assert not ok
        assert any(e["code"] == "ref_character_unknown" for e in errors)


# ---------------- renumber_global ----------------

class TestRenumberGlobal:
    def test_renumbers_groups_and_shots_continuously(self):
        parsed = {"shot_groups": [
            {"group_id": "old_g2", "shots": [
                {"shot_id": "x5", "shot_number": 9, "duration": 2.0},
                {"shot_id": "x6", "shot_number": 10, "duration": 3.5},
            ]},
            {"group_id": "old_g1", "shots": [
                {"shot_id": "x1", "shot_number": 1, "duration": 1.0},
            ]},
        ]}
        result = renumber_global(parsed)
        groups = result["shot_groups"]
        assert groups[0]["group_id"] == "grp_001"
        assert groups[1]["group_id"] == "grp_002"
        shots = [s for g in groups for s in g["shots"]]
        assert [s["shot_id"] for s in shots] == ["s001", "s002", "s003"]
        assert [s["shot_number"] for s in shots] == [1, 2, 3]
        # 总时长累加
        assert result["total_duration"] == 6
        assert result["metadata"]["total_shots"] == 3

    def test_empty_groups_safe(self):
        result = renumber_global({"shot_groups": []})
        assert result["metadata"]["total_shots"] == 0


# ---------------- strategy ----------------

class TestScriptSplitStrategy:
    def test_standard_strategy_default(self):
        strat = get_script_split_strategy("speed")
        assert isinstance(strat, StandardScriptSplitStrategy)

    def test_standard_strategy_none_mode(self):
        strat = get_script_split_strategy(None)  # type: ignore[arg-type]
        assert isinstance(strat, StandardScriptSplitStrategy)

    @pytest.mark.skipif(
        not __import__("config").constant.Edition.is_community(),
        reason="仅在社区版验证 quality 门面抛错",
    )
    def test_quality_mode_community_raises(self):
        """社区版调用 quality → 抛 StoryboardEnterpriseFeatureRequired。"""
        with pytest.raises(StoryboardEnterpriseFeatureRequired):
            get_script_split_strategy("quality")

    def test_standard_strategy_parallel_disabled(self):
        strat = StandardScriptSplitStrategy()
        assert strat.parallel_enabled is False

    def test_standard_strategy_compile_plan_passthrough(self):
        """标准策略 compile_plan 原样返回（社区版不做额外处理）。"""
        strat = StandardScriptSplitStrategy()
        plan = {"segments": [{"segment_id": "s1", "block_ids": ["block_0001"]}]}
        assert strat.compile_plan(plan, []) is plan
