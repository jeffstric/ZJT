"""剧本拆分 presentation 单人画内门禁测试。"""

from llm.script_split_qc_agent import run_rule_qc


def _parsed_shot(*, presentation, characters_present, dialogue):
    return {
        "characters": [
            {"id": "char_001", "name": "甲"},
            {"id": "char_002", "name": "乙"},
        ],
        "shot_groups": [{
            "group_id": "grp_001",
            "shots": [{
                "shot_number": 1,
                "duration": 3,
                "presentation": presentation,
                "characters_present": characters_present,
                "dialogue": dialogue,
                "opening_frame_description": "【【甲】】位于画面中央并面向镜头，【【乙】】位于画面右侧。",
            }],
        }],
    }


def _issue_codes(report):
    return {issue.code for issue in report.issues}


def test_qc_rejects_digital_human_without_visible_character():
    parsed = _parsed_shot(
        presentation="digital_human",
        characters_present=[],
        dialogue=[{"character_id": "char_001", "text": "画外音"}],
    )

    report = run_rule_qc(parsed)

    assert "DH_WITHOUT_VISIBLE_CHARACTER" in _issue_codes(report)


def test_qc_rejects_digital_human_with_multiple_visible_characters():
    parsed = _parsed_shot(
        presentation="digital_human",
        characters_present=["char_001", "char_002"],
        dialogue=[{"character_id": "char_001", "text": "听我说"}],
    )

    report = run_rule_qc(parsed)

    assert "MULTI_CHARACTER_DH" in _issue_codes(report)


def test_qc_rejects_digital_human_when_speaker_is_offscreen():
    parsed = _parsed_shot(
        presentation="digital_human",
        characters_present=["char_002"],
        dialogue=[{"character_id": "char_001", "text": "画外音"}],
    )

    report = run_rule_qc(parsed)

    assert "DH_SPEAKER_NOT_VISIBLE" in _issue_codes(report)
