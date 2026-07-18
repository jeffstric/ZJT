"""Tests for validate_parsed_script (shot_groups 协议修正回归).

见 docs/script/script_parser_incremental_split_design.md §20.1。
验证旧的扁平 shots 校验已修正为 shot_groups[].shots[] 协议。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from llm.script_parser import validate_parsed_script


def test_valid_shot_groups_structure():
    data = {
        "characters": [{"id": "char_001", "name": "苏晚"}],
        "locations": [{"id": "loc_001", "name": "主卧"}],
        "shot_groups": [{
            "group_id": "grp_001",
            "shots": [
                {"shot_id": "s001", "duration": 5, "location_id": "loc_001",
                 "characters_present": ["char_001"]},
            ],
        }],
    }
    ok, msg = validate_parsed_script(data)
    assert ok, msg


def test_missing_shot_groups_rejected():
    data = {"characters": [], "locations": []}
    ok, msg = validate_parsed_script(data)
    assert not ok
    assert "shot_groups" in msg


def test_missing_top_level_key():
    data = {"characters": [], "shot_groups": []}  # 缺 locations
    ok, msg = validate_parsed_script(data)
    assert not ok
    assert "locations" in msg


def test_invalid_character_ref_in_shot():
    data = {
        "characters": [{"id": "char_001", "name": "苏晚"}],
        "locations": [],
        "shot_groups": [{"shots": [
            {"shot_id": "s001", "duration": 5, "characters_present": ["char_999"]},
        ]}],
    }
    ok, msg = validate_parsed_script(data)
    assert not ok
    assert "char_999" in msg


def test_invalid_location_ref_in_shot():
    data = {
        "characters": [],
        "locations": [{"id": "loc_001", "name": "主卧"}],
        "shot_groups": [{"shots": [
            {"shot_id": "s001", "duration": 5, "location_id": "loc_999"},
        ]}],
    }
    ok, msg = validate_parsed_script(data)
    assert not ok
    assert "loc_999" in msg


def test_null_location_id_allowed():
    """location_id 可为 null（sanitize 后悬空置空）。"""
    data = {
        "characters": [],
        "locations": [],
        "shot_groups": [{"shots": [
            {"shot_id": "s001", "duration": 5, "location_id": None},
        ]}],
    }
    ok, msg = validate_parsed_script(data)
    assert ok, msg
