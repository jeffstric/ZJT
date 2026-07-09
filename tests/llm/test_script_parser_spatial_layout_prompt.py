from pathlib import Path

from llm.script_parser import (
    SCRIPT_PARSER_SYSTEM_PROMPT,
    repair_spatial_layout_continuity,
)


def test_script_parser_prompt_requires_spatial_layout_schema():
    prompt = SCRIPT_PARSER_SYSTEM_PROMPT

    assert "spatial_layout" in prompt
    assert "location_path" in prompt
    assert "containers" in prompt
    assert "loose_positions" in prompt
    assert "continuity" in prompt
    assert "真实" in prompt and "场景" in prompt and "道具" in prompt


def test_script_parser_prompt_preserves_secondary_characters_in_closeups():
    prompt = SCRIPT_PARSER_SYSTEM_PROMPT

    assert "focus_character_ids" in prompt
    assert "visibility" in prompt
    assert "framing_role" in prompt
    assert "secondary_continuity" in prompt
    assert "partial" in prompt
    assert "offscreen" in prompt
    assert "逐项核对上一镜头" in prompt
    assert "visible/partial" in prompt
    assert "changed_positions" in prompt
    assert "change_type" in prompt
    assert "exited_scene" in prompt


def test_split_multi_dialogue_prompt_allows_spatial_continuity_characters():
    source = Path("llm/script_parser.py").read_text(encoding="utf-8")

    assert "focus_character_ids" in source
    assert "secondary_continuity" in source
    assert "非说话角色" in source
    assert "空间连续性" in source
    assert "严禁把非说话角色写成发言主体" in source
    assert "characters_present 只剩 1 个角色" not in source
    assert "唯一在场角色" not in source
    assert "并与 `characters_present` 保持一致" not in source
    assert "SPATIAL_EXIT_KEYWORDS" not in source
    assert "_shot_text_mentions_character_exit" not in source


def test_repair_spatial_layout_carries_missing_previous_character_slot_as_offscreen():
    parsed = {
        "characters": [
            {"id": "char_001", "name": "奶昔_Milkshake", "character_db_id": 4},
            {"id": "char_002", "name": "奶酪_Cheese", "character_db_id": 5},
        ],
        "shot_groups": [
            {
                "group_id": "grp_001",
                "shots": [
                    {
                        "shot_id": "s001",
                        "characters_present": ["char_001", "char_002"],
                        "spatial_layout": {
                            "containers": [
                                {
                                    "container_type": "prop",
                                    "prop_id": "prop_001",
                                    "name": "泡泡蒸汽车",
                                    "area": "驾驶室",
                                    "slots": [
                                        {
                                            "slot": "驾驶座",
                                            "occupant_type": "character",
                                            "character_id": "char_001",
                                            "name": "奶昔_Milkshake",
                                            "visibility": "visible",
                                            "framing_role": "primary_subject",
                                        },
                                        {
                                            "slot": "副驾驶座",
                                            "occupant_type": "character",
                                            "character_id": "char_002",
                                            "name": "奶酪_Cheese",
                                            "visibility": "visible",
                                            "framing_role": "primary_subject",
                                        },
                                    ],
                                }
                            ],
                            "continuity": {"unchanged_slots": []},
                        },
                    },
                    {
                        "shot_id": "s002",
                        "characters_present": ["char_001"],
                        "focus_character_ids": ["char_001"],
                        "spatial_layout": {
                            "containers": [
                                {
                                    "container_type": "prop",
                                    "prop_id": "prop_001",
                                    "name": "泡泡蒸汽车",
                                    "area": "驾驶室",
                                    "slots": [
                                        {
                                            "slot": "驾驶座",
                                            "occupant_type": "character",
                                            "character_id": "char_001",
                                            "name": "奶昔_Milkshake",
                                            "visibility": "visible",
                                            "framing_role": "primary_subject",
                                        }
                                    ],
                                }
                            ],
                            "continuity": {"unchanged_slots": ["驾驶座"]},
                        },
                    },
                ],
            }
        ],
    }

    result = repair_spatial_layout_continuity(parsed)
    shot = result["shot_groups"][0]["shots"][1]
    slots = shot["spatial_layout"]["containers"][0]["slots"]
    carried = next(slot for slot in slots if slot.get("character_id") == "char_002")

    assert carried["slot"] == "副驾驶座"
    assert carried["visibility"] == "offscreen"
    assert carried["framing_role"] == "offscreen_continuity"
    assert shot["characters_present"] == ["char_001"]
    assert "副驾驶座" in shot["spatial_layout"]["continuity"]["unchanged_slots"]


def test_repair_spatial_layout_uses_llm_structured_changed_positions_instead_of_text_keywords():
    parsed = {
        "characters": [
            {"id": "char_001", "name": "奶昔_Milkshake"},
            {"id": "char_002", "name": "奶酪_Cheese"},
        ],
        "shot_groups": [
            {
                "group_id": "grp_001",
                "shots": [
                    {
                        "shot_id": "s001",
                        "spatial_layout": {
                            "containers": [
                                {
                                    "container_type": "prop",
                                    "prop_id": "prop_001",
                                    "name": "泡泡蒸汽车",
                                    "area": "驾驶室",
                                    "slots": [
                                        {
                                            "slot": "副驾驶座",
                                            "occupant_type": "character",
                                            "character_id": "char_002",
                                            "name": "奶酪_Cheese",
                                            "visibility": "visible",
                                            "framing_role": "primary_subject",
                                        }
                                    ],
                                }
                            ]
                        },
                    },
                    {
                        "shot_id": "s002",
                        "description": "Cheese gets out and heads toward the syrup area.",
                        "spatial_layout": {
                            "containers": [
                                {
                                    "container_type": "prop",
                                    "prop_id": "prop_001",
                                    "name": "泡泡蒸汽车",
                                    "area": "驾驶室",
                                    "slots": [],
                                }
                            ],
                            "continuity": {
                                "unchanged_slots": [],
                                "changed_positions": [
                                    {
                                        "character_id": "char_002",
                                        "from_container_id": "prop_001",
                                        "from_slot": "副驾驶座",
                                        "to_container_id": None,
                                        "to_slot": None,
                                        "change_type": "exited_scene",
                                        "reason": "角色离开原空间位置",
                                    }
                                ],
                            },
                        },
                    },
                ],
            }
        ],
    }

    result = repair_spatial_layout_continuity(parsed)
    slots = result["shot_groups"][0]["shots"][1]["spatial_layout"]["containers"][0]["slots"]

    assert slots == []
