from services.script_split_character_contract import (
    build_character_contract_snapshot,
    normalize_characters_by_db_id,
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
        strict=True,
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
        strict=True,
    )

    assert "character_prompt_name_invalid" in _codes(errors)
    assert "character_missing_from_image_prompt" in _codes(errors)


def test_correct_entity_name_but_short_video_prompt_is_rejected():
    errors = validate_segment_character_contract(
        _parsed(video_name="奶昔"),
        CONTRACT,
        {},
        strict=True,
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

    errors = validate_segment_character_contract(parsed, CONTRACT, {}, strict=True)

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

    errors = validate_segment_character_contract(parsed, CONTRACT, registry, strict=True)

    assert "character_name_mismatch" in _codes(errors)
    assert any(error.get("expected_name") == "奶昔_Milkshake" for error in errors)


def test_malformed_character_token_is_rejected():
    parsed = _parsed()
    parsed["shot_groups"][0]["shots"][0]["action"] = "【【奶昔_Milkshake】握紧项链"

    errors = validate_segment_character_contract(parsed, CONTRACT, {}, strict=True)

    assert "character_token_malformed" in _codes(errors)


def test_new_character_without_database_collision_can_establish_task_name():
    parsed = _parsed(character_name="新角色", image_name="新角色", video_name="新角色")
    parsed["characters"][0]["character_db_id"] = None

    assert validate_segment_character_contract(parsed, CONTRACT, {}) == []


def test_lenient_mode_passes_short_chinese_name_without_blocking(caplog):
    contract = {
        "version": 1,
        "world_id": 823,
        "characters": [{"character_db_id": 101, "canonical_name": "卢卡莫德里奇"}],
    }
    parsed = _parsed(character_name="莫德里奇", image_name="莫德里奇", video_name="莫德里奇")

    with caplog.at_level("WARNING", logger="services.script_split_character_contract"):
        errors = validate_segment_character_contract(parsed, contract, {})

    assert errors == []
    assert "角色契约校验放行" in caplog.text


def test_lenient_mode_passes_unknown_character_db_id(caplog):
    parsed = _parsed()
    parsed["characters"][0]["character_db_id"] = 999

    with caplog.at_level("WARNING", logger="services.script_split_character_contract"):
        errors = validate_segment_character_contract(parsed, CONTRACT, {})

    assert errors == []
    assert "角色契约校验放行" in caplog.text


def test_lenient_mode_passes_missing_prompt_tokens():
    parsed = _parsed()
    shot = parsed["shot_groups"][0]["shots"][0]
    shot["opening_frame_description"] = "近景：驾驶座区域。"
    shot["description"] = "镜头缓缓推进。"
    shot["action"] = "主角握紧项链。"

    assert validate_segment_character_contract(parsed, CONTRACT, {}) == []


def test_lenient_mode_passes_non_dict_payload():
    assert validate_segment_character_contract(None, CONTRACT, {}) == []


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


# ---- normalize_characters_by_db_id（方案A：db_id 为真值强制归一化）----

HP_CONTRACT = {
    "version": 1,
    "world_id": 2121,
    "characters": [
        {"character_db_id": 81397, "canonical_name": "哈利波特"},
        {"character_db_id": 81401, "canonical_name": "德拉科莉亚马尔福"},
    ],
}


def _hp_parsed(name, db_id):
    return {
        "characters": [{
            "id": "char_001",
            "character_db_id": db_id,
            "name": name,
        }],
        "shot_groups": [{
            "group_id": "grp_001",
            "shots": [{
                "shot_id": "shot_001",
                "characters_present": ["char_001"],
                "opening_frame_description": f"近景：【【{name}】】举起魔杖。",
                "scene_detail": "走廊光线昏暗。",
                "description": f"【【{name}】】直视前方。",
                "action": f"【【{name}】】后撤一步。",
                "dialogue": [{"text": f"【【{name}】】低声说：快跑。",
                              "character_name": f"【【{name}】】"}],
                "spatial_layout": {
                    "screen_composition": f"【【{name}】】位于画面中央偏下",
                    "description": f"机位距【【{name}】】约1.5米",
                },
            }],
        }],
    }


def test_normalize_short_name_by_db_id_rewrites_name_and_tokens():
    """LLM 回填 db_id 正确但输出简称「哈利」：归一化 name 并重写全部标记。"""
    parsed = _hp_parsed("哈利", 81397)

    renamed = normalize_characters_by_db_id(parsed, HP_CONTRACT)

    assert renamed == {"哈利": "哈利波特"}
    assert parsed["characters"][0]["name"] == "哈利波特"
    shot = parsed["shot_groups"][0]["shots"][0]
    assert shot["opening_frame_description"] == "近景：【【哈利波特】】举起魔杖。"
    assert shot["description"] == "【【哈利波特】】直视前方。"
    assert shot["action"] == "【【哈利波特】】后撤一步。"
    assert shot["dialogue"][0]["text"] == "【【哈利波特】】低声说：快跑。"
    # 对白说话人与机位锚文本（camera_anchor 来源）同样全树替换
    assert shot["dialogue"][0]["character_name"] == "【【哈利波特】】"
    assert shot["spatial_layout"]["screen_composition"] == "【【哈利波特】】位于画面中央偏下"
    assert shot["spatial_layout"]["description"] == "机位距【【哈利波特】】约1.5米"


def test_normalize_separator_variant_by_db_id():
    """分隔符变体「德拉科莉亚·马尔福」→ 库内无点全名。"""
    parsed = _hp_parsed("德拉科莉亚·马尔福", 81401)

    renamed = normalize_characters_by_db_id(parsed, HP_CONTRACT)

    assert renamed == {"德拉科莉亚·马尔福": "德拉科莉亚马尔福"}
    assert parsed["characters"][0]["name"] == "德拉科莉亚马尔福"


def test_normalize_then_contract_validate_passes():
    """归一化后契约校验不再报 name mismatch / 提示词标记非法。"""
    parsed = _hp_parsed("哈利", 81397)

    normalize_characters_by_db_id(parsed, HP_CONTRACT)

    assert validate_segment_character_contract(parsed, HP_CONTRACT, {}, strict=True) == []


def test_normalize_skips_when_old_name_is_another_character_full_name():
    """旧名恰为库内另一角色完整名：替换标记会误伤该角色，跳过归一化。"""
    contract = {
        "version": 1,
        "world_id": 2121,
        "characters": [
            {"character_db_id": 1, "canonical_name": "哈利波特"},
            {"character_db_id": 2, "canonical_name": "哈利"},
        ],
    }
    parsed = _hp_parsed("哈利", 1)

    renamed = normalize_characters_by_db_id(parsed, contract)

    assert renamed == {}
    assert parsed["characters"][0]["name"] == "哈利"
    assert parsed["shot_groups"][0]["shots"][0]["action"] == "【【哈利】】后撤一步。"


def test_normalize_noop_cases():
    """db_id 未命中契约 / db_id 为空 / 名称已一致：均不做任何修改。"""
    unknown_db = _hp_parsed("哈利", 999)
    assert normalize_characters_by_db_id(unknown_db, HP_CONTRACT) == {}
    assert unknown_db["characters"][0]["name"] == "哈利"

    no_db = _hp_parsed("新角色", None)
    assert normalize_characters_by_db_id(no_db, HP_CONTRACT) == {}
    assert no_db["characters"][0]["name"] == "新角色"

    matched = _hp_parsed("哈利波特", 81397)
    assert normalize_characters_by_db_id(matched, HP_CONTRACT) == {}

    assert normalize_characters_by_db_id({}, HP_CONTRACT) == {}
    assert normalize_characters_by_db_id(_hp_parsed("哈利", 81397), None) == {}


def test_normalize_fills_missing_name_from_contract():
    """db_id 正确但 name 缺失：直接补契约完整名（无旧名可登记）。"""
    parsed = _hp_parsed("", 81397)
    parsed["characters"][0]["name"] = None

    renamed = normalize_characters_by_db_id(parsed, HP_CONTRACT)

    assert renamed == {}
    assert parsed["characters"][0]["name"] == "哈利波特"


def test_normalize_skips_conflicting_renamed_target():
    """同名旧名映射到不同完整名：保留首个映射，后者不改写。"""
    contract = {
        "version": 1,
        "world_id": 2121,
        "characters": [
            {"character_db_id": 1, "canonical_name": "哈利波特"},
            {"character_db_id": 2, "canonical_name": "哈利·波特"},
        ],
    }
    parsed = {
        "characters": [
            {"id": "char_001", "character_db_id": 1, "name": "哈利"},
            {"id": "char_002", "character_db_id": 2, "name": "哈利"},
        ],
        "shot_groups": [],
    }

    renamed = normalize_characters_by_db_id(parsed, contract)

    assert renamed == {"哈利": "哈利波特"}
    assert parsed["characters"][0]["name"] == "哈利波特"
    assert parsed["characters"][1]["name"] == "哈利"
