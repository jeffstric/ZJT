"""Tests for script_split_registry (global ID + spatial reference validation).

见 docs/script/script_parser_incremental_split_design.md §20.1。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.script_split_registry import (
    AcceptedRegistry,
    rewrite_segment_entity_ids,
    validate_segment_entities,
    validate_segment_spatial_references,
    renumber_global,
)


# ---- 全局 ID 注册表 ----

def test_registry_id_reservations_start_at_001():
    reg = AcceptedRegistry()
    res = reg.id_reservations()
    assert res["character_start"] == "char_001"
    assert res["location_start"] == "loc_001"
    assert res["prop_start"] == "prop_001"


def test_commit_entity_advances_cursor():
    reg = AcceptedRegistry()
    reg.commit_entity("character", "char_001", {"name": "苏晚"})
    assert reg.id_reservations()["character_start"] == "char_002"
    # 找回
    assert reg.find_by_name("character", "苏晚") == "char_001"
    assert reg.find_by_name("character", "【【苏晚】】") == "char_001"  # 标记去除后归一


def test_commit_entity_skips_gap():
    """模型用了 char_005，游标应跳到 006 而非 002。"""
    reg = AcceptedRegistry()
    reg.commit_entity("character", "char_005", {"name": "林诚"})
    assert reg.id_reservations()["character_start"] == "char_006"


def test_find_by_db_id():
    reg = AcceptedRegistry()
    reg.commit_entity("location", "loc_001", {"name": "主卧", "location_db_id": 123})
    assert reg.find_by_db_id("location", 123) == "loc_001"
    assert reg.find_by_db_id("location", "123") == "loc_001"


# ---- 单段实体校验 ----

def test_validate_entities_new_uses_reserved_id():
    reg = AcceptedRegistry()
    seg = {"characters": [{"id": "char_001", "name": "苏晚"}]}
    ok, errors = validate_segment_entities(seg, reg)
    assert ok, errors


def test_validate_entities_new_below_reserved_rejected():
    """新实体复用了已占用编号（char_001 已提交，新段又用 char_001 当新实体）。"""
    reg = AcceptedRegistry()
    reg.commit_entity("character", "char_001", {"name": "苏晚"})
    # 段里给了 char_001 但名字不同（视为新实体）
    seg = {"characters": [{"id": "char_001", "name": "林诚"}]}
    ok, errors = validate_segment_entities(seg, reg)
    assert not ok
    assert any(e["code"] == "character_id_not_reserved" for e in errors)


def test_validate_entities_reuse_existing_id_ok():
    reg = AcceptedRegistry()
    reg.commit_entity("character", "char_001", {"name": "苏晚"})
    # 第二段复用 char_001 且名字匹配
    seg = {"characters": [{"id": "char_001", "name": "苏晚"}]}
    ok, errors = validate_segment_entities(seg, reg)
    assert ok, errors


def test_validate_entities_reuse_wrong_id_rejected():
    """同名实体应复用 char_001 但模型给了 char_002。"""
    reg = AcceptedRegistry()
    reg.commit_entity("character", "char_001", {"name": "苏晚"})
    seg = {"characters": [{"id": "char_002", "name": "苏晚"}]}
    ok, errors = validate_segment_entities(seg, reg)
    assert not ok
    assert any(e["code"] == "character_id_should_reuse" for e in errors)


def test_validate_entities_bad_id_format():
    reg = AcceptedRegistry()
    seg = {"characters": [{"id": "charlie_1", "name": "苏晚"}]}
    ok, errors = validate_segment_entities(seg, reg)
    assert not ok
    assert any(e["code"] == "character_id_format_invalid" for e in errors)


# ---- rewrite_segment_entity_ids ----

def test_rewrite_tmp_location_to_reserved_id():
    reg = AcceptedRegistry()
    reg.commit_entity("location", "loc_001", {"name": "大堂", "location_db_id": 565})
    reg.commit_entity("location", "loc_002", {"name": "走廊", "location_db_id": 798})
    reg.commit_entity("location", "loc_003", {"name": "套房", "location_db_id": 819})
    reg.commit_entity("location", "loc_004", {"name": "前台", "location_db_id": 794})
    # 预留 loc_005
    seg = {
        "locations": [
            {"id": "loc_001", "name": "大堂", "location_db_id": 565},
            {
                "id": "loc_tmp_storage",
                "name": "储物间",
                "location_db_id": None,
                "parent_id": "loc_001",
            },
        ],
        "shot_groups": [{
            "shots": [{"location_id": "loc_tmp_storage", "characters_present": []}],
        }],
    }
    rewrite_segment_entity_ids(seg, reg)
    assert seg["locations"][1]["id"] == "loc_005"
    assert seg["locations"][1]["parent_id"] == "loc_001"
    assert seg["shot_groups"][0]["shots"][0]["location_id"] == "loc_005"
    ok, errors = validate_segment_entities(seg, reg)
    assert ok, errors


def test_rewrite_should_reuse_prop_by_name():
    reg = AcceptedRegistry()
    reg.commit_entity("prop", "prop_001", {"name": "工牌"})
    seg = {
        "props": [{"id": "prop_005", "name": "工牌"}],
        "shot_groups": [{
            "shots": [{"props_present": ["prop_005"]}],
        }],
    }
    rewrite_segment_entity_ids(seg, reg)
    assert seg["props"][0]["id"] == "prop_001"
    assert seg["shot_groups"][0]["shots"][0]["props_present"] == ["prop_001"]
    ok, errors = validate_segment_entities(seg, reg)
    assert ok, errors


def test_rewrite_not_reserved_location_gets_new_id():
    reg = AcceptedRegistry()
    reg.commit_entity("location", "loc_001", {"name": "大堂"})
    # start=2, model wrongly uses loc_001 for a different new place name already taken id
    seg = {
        "locations": [
            {"id": "loc_001", "name": "大堂"},
            {"id": "loc_001", "name": "神秘密室"},  # 撞号且不同名 → 应发 loc_002
        ],
    }
    # two entities can't share same list entry easily - second as wrong low id
    seg = {
        "locations": [
            {"id": "loc_001", "name": "大堂"},
            {"id": "loc_tmp_secret", "name": "神秘密室"},
        ],
        "shot_groups": [],
    }
    rewrite_segment_entity_ids(seg, reg)
    assert seg["locations"][0]["id"] == "loc_001"
    assert seg["locations"][1]["id"] == "loc_002"
    ok, errors = validate_segment_entities(seg, reg)
    assert ok, errors


def test_rewrite_two_tmp_locations_get_distinct_ids():
    reg = AcceptedRegistry()
    reg.commit_entity("location", "loc_001", {"name": "大堂"})
    seg = {
        "locations": [
            {"id": "loc_tmp_a", "name": "阳台内侧"},
            {"id": "loc_tmp_b", "name": "储物间"},
        ],
        "shot_groups": [{
            "shots": [
                {"location_id": "loc_tmp_a"},
                {"location_id": "loc_tmp_b"},
            ],
        }],
    }
    rewrite_segment_entity_ids(seg, reg)
    ids = {e["id"] for e in seg["locations"]}
    assert ids == {"loc_002", "loc_003"}
    assert seg["shot_groups"][0]["shots"][0]["location_id"] in ids
    assert seg["shot_groups"][0]["shots"][1]["location_id"] in ids
    assert seg["shot_groups"][0]["shots"][0]["location_id"] != seg["shot_groups"][0]["shots"][1]["location_id"]
    ok, errors = validate_segment_entities(seg, reg)
    assert ok, errors


# ---- 空间引用校验 ----

def _build_registry_with_space():
    reg = AcceptedRegistry()
    reg.commit_entity("character", "char_001", {"name": "苏晚"})
    reg.commit_entity("prop", "prop_001", {"name": "车"})
    reg.commit_entity("location", "loc_001", {"name": "主卧"})
    reg.spatial_world = {
        "space_units": [{
            "space_unit_id": "space_loc_001_room",
            "owner_id": "loc_001",
            "location_ids": ["loc_001"],
            "coordinate_frame": {"frame_id": "frame_001"},
            "anchors": [{"anchor_id": "bed_left"}],
        }]
    }
    return reg


def test_validate_spatial_valid_references():
    reg = _build_registry_with_space()
    seg = {
        "spatial_world": {"space_units": []},
        "shot_groups": [{
            "shots": [{
                "shot_id": "s001",
                "spatial_layout": {
                    "space_unit_refs": ["space_loc_001_room"],
                    "camera_pose": {"space_unit_id": "space_loc_001_room"},
                    "camera_anchor": {"relative_to_character": {"character_id": "char_001"}},
                    "location_path": [{"location_id": "loc_001"}],
                    "containers": [{
                        "prop_id": "prop_001",
                        "slots": [{
                            "space_unit_id": "space_loc_001_room",
                            "anchor_id": "bed_left",
                            "character_id": "char_001",
                        }],
                    }],
                    "loose_positions": [],
                    "continuity": {"changed_positions": []},
                },
            }],
        }],
    }
    ok, errors = validate_segment_spatial_references(seg, reg)
    assert ok, errors


def test_validate_spatial_accepts_entities_declared_in_current_segment():
    reg = AcceptedRegistry()
    seg = {
        "characters": [{"id": "char_001", "name": "苏晚"}],
        "locations": [{"id": "loc_001", "name": "主卧"}],
        "props": [{"id": "prop_001", "name": "木桌"}],
        "spatial_world": {"space_units": []},
        "shot_groups": [{
            "shots": [{
                "shot_id": "s001",
                "spatial_layout": {
                    "camera_anchor": {
                        "relative_to_character": {"character_id": "char_001"},
                    },
                    "location_path": [{"location_id": "loc_001"}],
                    "containers": [{
                        "prop_id": "prop_001",
                        "slots": [{"character_id": "char_001"}],
                    }],
                    "loose_positions": [{"character_id": "char_001"}],
                    "continuity": {"changed_positions": []},
                },
            }],
        }],
    }

    ok, errors = validate_segment_spatial_references(seg, reg)

    assert ok, errors
    assert reg.characters == {}
    assert reg.locations == {}
    assert reg.props == {}


def test_validate_spatial_unknown_space_unit():
    reg = _build_registry_with_space()
    seg = {
        "spatial_world": {"space_units": []},
        "shot_groups": [{"shots": [{
            "shot_id": "s001",
            "spatial_layout": {"space_unit_refs": ["space_unknown"]},
        }]}],
    }
    ok, errors = validate_segment_spatial_references(seg, reg)
    assert not ok
    assert any(e["code"] == "ref_space_unit_unknown" for e in errors)


def test_validate_spatial_unknown_character():
    reg = _build_registry_with_space()
    seg = {
        "spatial_world": {"space_units": []},
        "shot_groups": [{"shots": [{
            "shot_id": "s001",
            "spatial_layout": {
                "camera_anchor": {"relative_to_character": {"character_id": "char_999"}},
            },
        }]}],
    }
    ok, errors = validate_segment_spatial_references(seg, reg)
    assert not ok
    assert any(e["code"] == "ref_character_unknown" for e in errors)


def test_validate_spatial_unknown_anchor():
    reg = _build_registry_with_space()
    seg = {
        "spatial_world": {"space_units": []},
        "shot_groups": [{"shots": [{
            "shot_id": "s001",
            "spatial_layout": {
                "containers": [{
                    "prop_id": "prop_001",
                    "slots": [{
                        "space_unit_id": "space_loc_001_room",
                        "anchor_id": "nonexistent_anchor",
                    }],
                }],
            },
        }]}],
    }
    ok, errors = validate_segment_spatial_references(seg, reg)
    assert not ok
    assert any(e["code"] == "ref_anchor_unknown" for e in errors)


def test_validate_spatial_changed_position_unknown_prop():
    reg = _build_registry_with_space()
    seg = {
        "spatial_world": {"space_units": []},
        "shot_groups": [{"shots": [{
            "shot_id": "s001",
            "spatial_layout": {
                "continuity": {"changed_positions": [{
                    "character_id": "char_001",
                    "from_container_id": "prop_999",
                }]},
            },
        }]}],
    }
    ok, errors = validate_segment_spatial_references(seg, reg)
    assert not ok
    assert any(e["code"] == "ref_prop_unknown" for e in errors)


# ---- 合并重排 ----

def test_renumber_global():
    parsed = {
        "shot_groups": [
            {"group_id": "old1", "shots": [
                {"shot_id": "x1", "shot_number": 99, "duration": 5},
                {"shot_id": "x2", "shot_number": 98, "duration": 3},
            ]},
            {"group_id": "old2", "shots": [
                {"shot_id": "x3", "shot_number": 97, "duration": 7},
            ]},
        ],
        "metadata": {},
    }
    result = renumber_global(parsed)
    assert result["shot_groups"][0]["group_id"] == "grp_001"
    assert result["shot_groups"][1]["group_id"] == "grp_002"
    shots = [s for g in result["shot_groups"] for s in g["shots"]]
    assert [s["shot_id"] for s in shots] == ["s001", "s002", "s003"]
    assert [s["shot_number"] for s in shots] == [1, 2, 3]
    assert result["total_duration"] == 15
    assert result["metadata"]["total_shots"] == 3
