"""compile_quality_plan：inherit 强制 out=in，mode=none 允许段边界不连续。"""
import pytest

from enterprise.services.script_split_quality.contract import (
    QualityPlanError,
    compile_quality_plan,
)


def _anchors_for(*block_ids: str):
    return [{"block_id": bid, "content": f"text-{bid}"} for bid in block_ids]


def _base_entities():
    return {
        "characters": [
            {"character_key": "character:lin", "name": "林晓", "description": "主角"},
            {"character_key": "character:zhao", "name": "赵先生", "description": "客人"},
        ],
        "locations": [
            {"location_key": "location:lobby", "name": "大堂", "description": "酒店大堂"},
            {"location_key": "location:corridor", "name": "走廊", "description": "套房走廊"},
        ],
        "props": [],
    }


def _pos(space, container, slot):
    return {
        "space_unit_id": space,
        "container_id": container,
        "slot_id": slot,
    }


def _char_state(*items):
    """items: (character_key, space, container, slot)"""
    return {
        "characters": [
            {
                "character_key": key,
                **_pos(space, container, slot),
            }
            for key, space, container, slot in items
        ]
    }


def test_mode_none_allows_discontinuous_boundary():
    """mode=none 的后段可不与前段 out 对齐（硬切/时间跳）。"""
    lobby = ("character:lin", "su_lobby", "cont_lobby", "slot_desk")
    corridor = ("character:lin", "su_corridor", "cont_corridor", "slot_path")
    plan = {
        "schema_version": 2,
        "entities": _base_entities(),
        "spatial_world": {"space_units": []},
        "segments": [
            {
                "segment_id": "seg_0001",
                "title": "大堂",
                "summary": "大堂结束",
                "block_ids": ["block_0001"],
                "continuity_in": _char_state(lobby),
                "continuity_out": _char_state(lobby),
                "state_changes": [],
                "spatial_dependency": {
                    "mode": "none",
                    "reason": "开篇",
                },
            },
            {
                "segment_id": "seg_0002",
                "title": "走廊硬切",
                "summary": "时间跳后走廊",
                "block_ids": ["block_0002"],
                "continuity_in": _char_state(corridor),  # 与 seg1 out 不同
                "continuity_out": _char_state(corridor),
                "state_changes": [],
                "spatial_dependency": {
                    "mode": "none",
                    "reason": "时间跳跃后的独立场景",
                },
            },
        ],
    }
    compiled = compile_quality_plan(plan, _anchors_for("block_0001", "block_0002"))
    assert len(compiled["segments"]) == 2
    assert compiled["segments"][1]["spatial_dependency"]["mode"] == "none"
    # character_key 已编译为 character_id
    assert compiled["segments"][1]["continuity_in"]["characters"][0]["character_id"] == "char_001"
    assert (
        compiled["segments"][1]["continuity_in"]["characters"][0]["space_unit_id"]
        == "su_corridor"
    )


def test_inherit_requires_continuity_in_match_upstream_out():
    """mode=inherit 时 continuity_in 必须等于 from 段 continuity_out。"""
    lobby = ("character:lin", "su_lobby", "cont_lobby", "slot_desk")
    corridor = ("character:lin", "su_corridor", "cont_corridor", "slot_path")
    plan = {
        "schema_version": 2,
        "entities": _base_entities(),
        "spatial_world": {"space_units": []},
        "segments": [
            {
                "segment_id": "seg_0001",
                "title": "大堂",
                "summary": "大堂",
                "block_ids": ["block_0001"],
                "continuity_in": _char_state(lobby),
                "continuity_out": _char_state(lobby),
                "state_changes": [],
                "spatial_dependency": {"mode": "none", "reason": "开篇"},
            },
            {
                "segment_id": "seg_0002",
                "title": "接大堂",
                "summary": "错误：入点已在走廊",
                "block_ids": ["block_0002"],
                "continuity_in": _char_state(corridor),
                "continuity_out": _char_state(corridor),
                "state_changes": [],
                "spatial_dependency": {
                    "mode": "inherit",
                    "from_segment_id": "seg_0001",
                    "camera_pose_policy": "reference",
                    "reason": "同场景连续",
                },
            },
        ],
    }
    with pytest.raises(QualityPlanError, match="continuity_out does not match seg_0002"):
        compile_quality_plan(plan, _anchors_for("block_0001", "block_0002"))


def test_inherit_passes_when_in_equals_upstream_out():
    lobby = ("character:lin", "su_lobby", "cont_lobby", "slot_desk")
    plan = {
        "schema_version": 2,
        "entities": _base_entities(),
        "spatial_world": {"space_units": []},
        "segments": [
            {
                "segment_id": "seg_0001",
                "title": "大堂",
                "summary": "大堂",
                "block_ids": ["block_0001"],
                "continuity_in": _char_state(lobby),
                "continuity_out": _char_state(lobby),
                "state_changes": [],
                "spatial_dependency": {"mode": "none", "reason": "开篇"},
            },
            {
                "segment_id": "seg_0002",
                "title": "大堂续",
                "summary": "连续",
                "block_ids": ["block_0002"],
                "continuity_in": _char_state(lobby),
                "continuity_out": _char_state(lobby),
                "state_changes": [],
                "spatial_dependency": {
                    "mode": "inherit",
                    "from_segment_id": "seg_0001",
                    "camera_pose_policy": "reference",
                    "reason": "同场景连续",
                },
            },
        ],
    }
    compiled = compile_quality_plan(plan, _anchors_for("block_0001", "block_0002"))
    assert compiled["segments"][1]["spatial_dependency"]["from_segment_id"] == "seg_0001"


def test_inherit_matches_from_segment_not_list_predecessor():
    """inherit 校验对准 from_segment_id 的 out，不是列表紧邻前一段。"""
    lobby = ("character:lin", "su_lobby", "cont_lobby", "slot_desk")
    other = ("character:zhao", "su_corridor", "cont_corridor", "slot_path")
    plan = {
        "schema_version": 2,
        "entities": _base_entities(),
        "spatial_world": {"space_units": []},
        "segments": [
            {
                "segment_id": "seg_0001",
                "title": "大堂线",
                "summary": "主线",
                "block_ids": ["block_0001"],
                "continuity_in": _char_state(lobby),
                "continuity_out": _char_state(lobby),
                "state_changes": [],
                "spatial_dependency": {"mode": "none", "reason": "开篇"},
            },
            {
                # 独立支线，与 seg1 不连续
                "segment_id": "seg_0002",
                "title": "支线",
                "summary": "独立",
                "block_ids": ["block_0002"],
                "continuity_in": _char_state(other),
                "continuity_out": _char_state(other),
                "state_changes": [],
                "spatial_dependency": {
                    "mode": "none",
                    "reason": "独立人物线",
                },
            },
            {
                # 接回 seg1，不接 seg2
                "segment_id": "seg_0003",
                "title": "回主线",
                "summary": "继承 seg1",
                "block_ids": ["block_0003"],
                "continuity_in": _char_state(lobby),
                "continuity_out": _char_state(lobby),
                "state_changes": [],
                "spatial_dependency": {
                    "mode": "inherit",
                    "from_segment_id": "seg_0001",
                    "camera_pose_policy": "reference",
                    "reason": "接回大堂主线",
                },
            },
        ],
    }
    compiled = compile_quality_plan(
        plan, _anchors_for("block_0001", "block_0002", "block_0003")
    )
    assert compiled["segments"][2]["spatial_dependency"]["from_segment_id"] == "seg_0001"


def test_compile_l0_rejects_planned_new_root_against_db():
    plan = {
        "schema_version": 2,
        "entities": {
            "characters": [
                {"character_key": "character:lin", "name": "林晓", "description": "主角"},
            ],
            "locations": [
                {
                    "location_key": "location:office",
                    "name": "酒店办公室",
                    "description": "新顶层",
                },
            ],
            "props": [],
        },
        "spatial_world": {"space_units": []},
        "segments": [
            {
                "segment_id": "seg_0001",
                "title": "开场",
                "summary": "开场",
                "block_ids": ["block_0001"],
                "continuity_in": {"characters": []},
                "continuity_out": {"characters": []},
                "state_changes": [],
                "spatial_dependency": {"mode": "none", "reason": "开篇"},
            },
        ],
    }
    with pytest.raises(QualityPlanError, match="new_root_location_forbidden"):
        compile_quality_plan(plan, _anchors_for("block_0001"), db_locations=[])


def test_compile_l0_accepts_db_matched_location_and_child():
    plan = {
        "schema_version": 2,
        "entities": {
            "characters": [
                {"character_key": "character:lin", "name": "林晓", "description": "主角"},
            ],
            "locations": [
                {
                    "location_key": "location:lobby",
                    "name": "城南酒店大堂",
                    "description": "大堂",
                },
                {
                    "location_key": "location:office",
                    "name": "酒店办公室",
                    "description": "办公室",
                    "parent_location_key": "location:lobby",
                },
            ],
            "props": [],
        },
        "spatial_world": {
            "space_units": [
                {"space_unit_id": "space_unit:lobby", "name": "城南酒店大堂"},
                {"space_unit_id": "space_unit:office", "name": "酒店办公室"},
            ]
        },
        "segments": [
            {
                "segment_id": "seg_0001",
                "title": "开场",
                "summary": "开场",
                "block_ids": ["block_0001"],
                "continuity_in": {"characters": []},
                "continuity_out": {"characters": []},
                "state_changes": [],
                "spatial_dependency": {"mode": "none", "reason": "开篇"},
            },
        ],
    }
    db = [{"id": 565, "name": "城南酒店大堂", "parent_id": None, "children": []}]
    compiled = compile_quality_plan(
        plan, _anchors_for("block_0001"), db_locations=db,
    )
    locs = compiled["compiled_registry"]["locations"]
    by_id = {item["id"]: item for item in locs}
    assert by_id["loc_001"]["location_db_id"] == 565
    assert by_id["loc_002"]["parent_id"] == "loc_001"
    assert by_id["loc_002"]["location_db_id"] is None
