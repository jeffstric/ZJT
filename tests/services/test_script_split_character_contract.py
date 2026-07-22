from services.script_split_character_contract import (
    build_character_contract_snapshot,
    validate_segment_character_contract,
)


CONTRACT = {
    "version": 1,
    "world_id": 823,
    "characters": [
        {
            "character_db_id": 101,
            "canonical_name": "奶昔_Milkshake",
        },
        {
            "character_db_id": 102,
            "canonical_name": "奶酪_Cheese",
        },
    ],
}


def _parsed(*, character_name="奶昔_Milkshake", image_name=None, video_name=None):
    image_name = image_name if image_name is not None else character_name
    video_name = video_name if video_name is not None else character_name
    return {
        "characters": [{
            "id": "char_001",
            "character_db_id": 101,
            "name": character_name,
        }],
        "shot_groups": [{
            "group_id": "grp_001",
            "shots": [{
                "shot_id": "shot_005",
                "characters_present": ["char_001"],
                "opening_frame_description": f"近景：【【{image_name}】】握住操作杆。",
                "scene_detail": "车厢内蓝色光芒增强。",
                "description": f"【【{video_name}】】直视前方。",
                "action": f"【【{video_name}】】握紧项链。",
            }],
        }],
    }


def _codes(errors):
    return {error["code"] for error in errors}


def test_full_canonical_character_name_passes_image_and_video_contract():
    assert validate_segment_character_contract(_parsed(), CONTRACT, {}) == []


def test_short_name_cannot_override_database_character_name():
    errors = validate_segment_character_contract(
        _parsed(character_name="奶昔", image_name="奶昔", video_name="奶昔"),
        CONTRACT,
        {},
    )

    assert "character_name_mismatch" in _codes(errors)
    assert "character_prompt_name_invalid" in _codes(errors)
    assert all(error["_hard_gate"] is True for error in errors)
    assert any(error.get("expected_name") == "奶昔_Milkshake" for error in errors)


def test_correct_entity_name_but_short_image_prompt_is_rejected():
    errors = validate_segment_character_contract(
        _parsed(image_name="奶昔"),
        CONTRACT,
        {},
    )

    assert "character_prompt_name_invalid" in _codes(errors)
    assert "character_missing_from_image_prompt" in _codes(errors)


def test_correct_entity_name_but_short_video_prompt_is_rejected():
    errors = validate_segment_character_contract(
        _parsed(video_name="奶昔"),
        CONTRACT,
        {},
    )

    assert "character_prompt_name_invalid" in _codes(errors)
    assert "character_missing_from_video_prompt" in _codes(errors)


def test_image_prompt_contract_uses_opening_frame_and_scene_detail_combination():
    parsed = _parsed()
    shot = parsed["shot_groups"][0]["shots"][0]
    shot["opening_frame_description"] = "近景：驾驶座区域。"
    shot["scene_detail"] = "背景中可见【【奶昔_Milkshake】】的轮廓。"

    assert validate_segment_character_contract(parsed, CONTRACT, {}) == []


def test_short_background_character_token_is_rejected_even_when_not_in_present_list():
    parsed = _parsed()
    parsed["shot_groups"][0]["shots"][0]["scene_detail"] = (
        "乘客座方向隐约有【【奶酪】】的轮廓。"
    )

    errors = validate_segment_character_contract(parsed, CONTRACT, {})

    assert any(
        error["code"] == "character_prompt_name_invalid"
        and error.get("actual_name") == "奶酪"
        and error.get("expected_name") == "奶酪_Cheese"
        for error in errors
    )


def test_registry_name_has_priority_over_current_segment_name():
    parsed = _parsed(character_name="奶昔", image_name="奶昔", video_name="奶昔")
    parsed["characters"][0]["character_db_id"] = None
    registry = {"characters": [{"id": "char_001", "name": "奶昔_Milkshake"}]}

    errors = validate_segment_character_contract(parsed, CONTRACT, registry)

    assert "character_name_mismatch" in _codes(errors)
    assert any(error.get("expected_name") == "奶昔_Milkshake" for error in errors)


def test_malformed_character_token_is_rejected():
    parsed = _parsed()
    parsed["shot_groups"][0]["shots"][0]["action"] = "【【奶昔_Milkshake】握紧项链"

    errors = validate_segment_character_contract(parsed, CONTRACT, {})

    assert "character_token_malformed" in _codes(errors)


def test_new_character_without_database_collision_can_establish_task_name():
    parsed = _parsed(character_name="新角色", image_name="新角色", video_name="新角色")
    parsed["characters"][0]["character_db_id"] = None

    assert validate_segment_character_contract(parsed, CONTRACT, {}) == []


def test_character_snapshot_loads_all_pages(monkeypatch):
    calls = []

    def fake_list_by_world(world_id, page, page_size, order_by, order_direction):
        calls.append((world_id, page, page_size, order_by, order_direction))
        start = (page - 1) * page_size
        end = min(start + page_size, 205)
        return {
            "total": 205,
            "data": [
                {"id": index + 1, "name": f"角色_{index + 1}"}
                for index in range(start, end)
            ],
        }

    monkeypatch.setattr(
        "services.script_split_character_contract.CharacterModel.list_by_world",
        fake_list_by_world,
    )

    snapshot = build_character_contract_snapshot(823)

    assert len(snapshot["characters"]) == 205
    assert [call[1] for call in calls] == [1, 2, 3]
