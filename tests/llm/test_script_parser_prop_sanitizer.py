from llm.script_parser import sanitize_parsed_prop_references


def test_sanitize_removes_hallucinated_prop_marker_not_in_db_or_script():
    parsed = {
        "props": [
            {"id": "prop_001", "name": "公文包", "props_db_id": 6754},
            {"id": "prop_002", "name": "扩音器", "props_db_id": None},
        ],
        "shot_groups": [
            {
                "group_id": "grp_001",
                "shots": [
                    {
                        "shot_id": "s001",
                        "props_present": ["prop_001", "prop_002"],
                        "opening_frame_description": "【【因凡蒂诺】】的〖〖扩音器〗〗掉在地上，〖〖公文包〗〗留在桌边。",
                        "scene_detail": "镜头掠过〖〖扩音器〗〗。",
                    }
                ],
            }
        ],
    }
    db_props = [
        {"id": 6754, "name": "公文包"},
        {"id": 6757, "name": "裁判哨子"},
    ]

    result = sanitize_parsed_prop_references(parsed, db_props, script_content="因凡蒂诺拿着公文包进入房间。")

    assert [prop["name"] for prop in result["props"]] == ["公文包"]
    shot = result["shot_groups"][0]["shots"][0]
    assert shot["props_present"] == ["prop_001"]
    assert "〖〖扩音器〗〗" not in shot["opening_frame_description"]
    assert "〖〖扩音器〗〗" not in shot["scene_detail"]
    assert "〖〖公文包〗〗" in shot["opening_frame_description"]


def test_sanitize_canonicalizes_unique_prop_suffix_to_db_prop_name():
    parsed = {
        "props": [
            {"id": "prop_001", "name": "哨子", "props_db_id": None},
        ],
        "shot_groups": [
            {
                "group_id": "grp_001",
                "shots": [
                    {
                        "shot_id": "s001",
                        "props_present": ["prop_001"],
                        "opening_frame_description": "【【裁判】】吹响〖〖哨子〗〗。",
                    }
                ],
            }
        ],
    }
    db_props = [{"id": 6757, "name": "裁判哨子"}]

    result = sanitize_parsed_prop_references(parsed, db_props, script_content="裁判吹响哨子。")

    assert result["props"][0]["name"] == "裁判哨子"
    assert result["props"][0]["props_db_id"] == 6757
    assert result["shot_groups"][0]["shots"][0]["opening_frame_description"] == "【【裁判】】吹响〖〖裁判哨子〗〗。"


def test_sanitize_keeps_new_prop_when_name_appears_in_script():
    parsed = {
        "props": [
            {"id": "prop_001", "name": "签名球衣", "props_db_id": None},
        ],
        "shot_groups": [
            {
                "group_id": "grp_001",
                "shots": [
                    {
                        "shot_id": "s001",
                        "props_present": ["prop_001"],
                        "opening_frame_description": "桌上放着〖〖签名球衣〗〗。",
                    }
                ],
            }
        ],
    }

    result = sanitize_parsed_prop_references(parsed, [], script_content="球员把签名球衣递给球迷。")

    assert result["props"][0]["name"] == "签名球衣"
    assert result["shot_groups"][0]["shots"][0]["props_present"] == ["prop_001"]
    assert "〖〖签名球衣〗〗" in result["shot_groups"][0]["shots"][0]["opening_frame_description"]
