import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.script_parser import reorganize_shot_groups


SCRIPT_PARSER_PATH = PROJECT_ROOT / "llm" / "script_parser.py"


def _shot(number, duration=5, location_id="loc_001"):
    return {
        "shot_id": f"s{number:03d}",
        "shot_number": number,
        "duration": duration,
        "location_id": location_id,
    }


def _shot_numbers(result):
    return [
        [shot["shot_number"] for shot in group["shots"]]
        for group in result["shot_groups"]
    ]


def test_reorganize_preserves_story_writer_scene_boundaries():
    parsed_data = {
        "shot_groups": [
            {
                "group_id": "grp_001",
                "group_name": "场景编号：A1 教室大厅 夜晚",
                "shots": [_shot(1, duration=6)],
            },
            {
                "group_id": "grp_002",
                "group_name": "场景编号：B1 陶艺吧 夜晚",
                "shots": [_shot(2, duration=6)],
            },
        ]
    }

    result = reorganize_shot_groups(parsed_data, max_group_duration=15)

    assert _shot_numbers(result) == [[1], [2]]


def test_reorganize_splits_overlong_scene_without_filling_from_next_scene():
    parsed_data = {
        "shot_groups": [
            {
                "group_id": "grp_001",
                "group_name": "[场景 教室大厅 夜晚] 场景编号：A1",
                "shots": [_shot(1, duration=8), _shot(2, duration=8)],
            },
            {
                "group_id": "grp_002",
                "group_name": "[场景 陶艺吧 夜晚] 场景编号：B1",
                "shots": [_shot(3, duration=4)],
            },
        ]
    }

    result = reorganize_shot_groups(parsed_data, max_group_duration=15)

    assert _shot_numbers(result) == [[1], [2], [3]]


def test_reorganize_uses_act_boundaries_when_scene_markers_are_absent():
    parsed_data = {
        "shot_groups": [
            {
                "group_id": "grp_001",
                "group_name": "第一幕：发现线索",
                "shots": [_shot(1, duration=5)],
            },
            {
                "group_id": "grp_002",
                "group_name": "第二幕：追问真相",
                "shots": [_shot(2, duration=5)],
            },
        ]
    }

    result = reorganize_shot_groups(parsed_data, max_group_duration=15)

    assert _shot_numbers(result) == [[1], [2]]


def test_prompt_contains_non_conflicting_storyboard_design_rules():
    parser_source = SCRIPT_PARSER_PATH.read_text(encoding="utf-8")

    assert '"narrative_purpose"' in parser_source
    assert "叙事目的必须从以下七类中选择" in parser_source
    for purpose in ("建立", "推进", "揭示", "强调", "过渡", "情绪", "反射"):
        assert purpose in parser_source
    assert "画面内容必须写可见动作" in parser_source
    assert "动作-反应结构" in parser_source
    assert "短镜优先并入同一场景或同一幕内的相邻镜头" in parser_source
    assert "短镜必须跨场景" not in parser_source


def test_prompt_requires_prop_marker_distinct_from_character_marker():
    parser_source = SCRIPT_PARSER_PATH.read_text(encoding="utf-8")

    assert "道具名称必须用〖〖道具名〗〗格式包裹" in parser_source
    assert "角色名称必须用【【角色名】】格式包裹" in parser_source
    assert "〖〖公文包〗〗【【德保罗】】" in parser_source
