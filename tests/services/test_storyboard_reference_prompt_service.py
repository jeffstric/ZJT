from services.storyboard_reference_prompt_service import (
    append_reference_legend,
    append_storyboard_visual_suffix,
    build_reference_legend,
    build_storyboard_reference_items,
    remove_storyboard_visual_suffix,
)


def test_visual_suffix_is_appended_at_tail_without_duplication():
    prompt = append_storyboard_visual_suffix(
        "镜头内容\n图片风格：电影写实\n参考图说明：图1是场景。",
        style="电影写实",
        composition_preference="三分法构图",
    )

    assert prompt.endswith("图片风格：电影写实\n构图倾向：三分法构图")
    assert prompt.count("图片风格：电影写实") == 1

    repeated = append_storyboard_visual_suffix(
        prompt,
        style="电影写实",
        composition_preference="三分法构图",
    )
    assert repeated == prompt

    cleaned = remove_storyboard_visual_suffix(
        repeated,
        style="电影写实",
        composition_preference="三分法构图",
    )
    assert cleaned == "镜头内容\n参考图说明：图1是场景。"


def test_reference_items_only_use_prompt_mentions_not_character_desc():
    prompt_json = {
        "scene_desc": "高空俯视，【【德保罗】】举着【【梅西】】位于最前方。",
        "character_desc": "德保罗、梅西、裁判、因凡蒂诺",
        "props": [
            {"name": "公文包", "db_id": 6754},
            {"name": "裁判哨子", "db_id": 6757},
        ],
        "location": {"id": 609, "name": "城市街道"},
    }
    characters = [
        {"id": 1, "name": "德保罗", "reference_image": "/upload/character/depaul.png"},
        {"id": 2, "name": "梅西", "reference_image": "/upload/character/messi.png"},
        {"id": 3, "name": "裁判", "reference_image": "/upload/character/referee.png"},
        {"id": 4, "name": "因凡蒂诺", "reference_image": "/upload/character/infantino.png"},
    ]
    props = [
        {"id": 6754, "name": "公文包", "reference_image": "/upload/props/briefcase.png"},
        {"id": 6757, "name": "裁判哨子", "reference_image": "/upload/props/whistle.png"},
    ]
    location = {"id": 609, "name": "城市街道", "reference_image": "/upload/location/street.png"}

    items = build_storyboard_reference_items(
        prompt_json=prompt_json,
        video_prompt="镜头继续跟随队伍冲刺。",
        characters=characters,
        props=props,
        location=location,
    )

    assert [(item["type"], item["name"]) for item in items] == [
        ("角色", "德保罗"),
        ("角色", "梅西"),
        ("场景", "城市街道"),
    ]
    assert [item["url"] for item in items] == [
        "/upload/character/depaul.png",
        "/upload/character/messi.png",
        "/upload/location/street.png",
    ]


def test_reference_items_include_prompt_matched_props_and_append_legend():
    prompt_json = {
        "scene_desc": "【【德保罗】】抓起〖〖公文包〗〗冲出房间。",
        "location": {"id": 7, "name": "布冯的房间"},
    }
    characters = [{"name": "德保罗", "reference_image": "/upload/character/depaul.png"}]
    props = [{"name": "公文包", "reference_image": "/upload/props/briefcase.png"}]
    location = {"name": "布冯的房间", "reference_image": "/upload/location/room.png"}

    items = build_storyboard_reference_items(
        prompt_json=prompt_json,
        video_prompt="",
        characters=characters,
        props=props,
        location=location,
    )
    prompt = append_reference_legend("请生成图片", items)

    assert [(item["type"], item["name"]) for item in items] == [
        ("角色", "德保罗"),
        ("道具", "公文包"),
        ("场景", "布冯的房间"),
    ]
    assert "参考图说明：图1是角色：德保罗。图2是道具：公文包。图3是场景：布冯的房间。" in prompt


def test_build_reference_legend_renders_empty_name_without_colon():
    # asset items (e.g. previous storyboard frame) carry an empty name and must
    # render as "图N是前一分镜。" without a trailing "：".
    items = [
        {"type": "角色", "name": "奶酪", "url": "https://cdn.test/cheese.png"},
        {"type": "角色", "name": "奶昔", "url": "https://cdn.test/milkshake.png"},
        {"type": "前一分镜", "name": "", "url": "https://cdn.test/prev.png"},
    ]
    legend = build_reference_legend(items)
    assert legend == (
        "参考图说明：图1是角色：奶酪。图2是角色：奶昔。图3是前一分镜。"
    )


def test_reference_selection_uses_valid_character_variant():
    prompt_json = {
        "scene_desc": "【【奶昔】】站在大厅。",
        "reference_selections": {
            "schema_version": 1,
            "characters": {
                "4": {
                    "character_id": 4,
                    "name": "奶昔",
                    "url": "/upload/character/milkshake_business.png",
                    "label": "商务服装",
                    "source": "reference_images",
                }
            },
        },
    }
    characters = [{
        "id": 4,
        "name": "奶昔",
        "reference_image": "/upload/character/milkshake.png",
        "reference_images": [
            {"url": "/upload/character/milkshake_business.png", "label": "商务服装"},
        ],
    }]

    items = build_storyboard_reference_items(
        prompt_json=prompt_json,
        characters=characters,
        location=None,
    )

    assert items[0]["url"] == "/upload/character/milkshake_business.png"
    assert items[0]["variant_label"] == "商务服装"
    assert "图1是角色：奶昔，商务服装" in build_reference_legend(items)


def test_reference_selection_rejects_cross_asset_url_and_falls_back():
    prompt_json = {
        "scene_desc": "【【奶昔】】站在大厅。",
        "reference_selections": {
            "schema_version": 1,
            "characters": {
                "4": {
                    "character_id": 4,
                    "name": "奶昔",
                    "url": "/upload/character/other_role.png",
                    "label": "伪造服装",
                    "source": "reference_images",
                }
            },
            "location": {
                "location_id": 9,
                "name": "大厅",
                "url": "/upload/location/other_room.png",
                "label": "伪造角度",
                "source": "reference_images",
            },
        },
    }
    characters = [{
        "id": 4,
        "name": "奶昔",
        "reference_image": "/upload/character/milkshake.png",
        "reference_images": [{"url": "/upload/character/milkshake_business.png", "label": "商务服装"}],
    }]
    location = {
        "id": 9,
        "name": "大厅",
        "reference_image": "/upload/location/hall.png",
        "reference_images": [{"url": "/upload/location/hall_right.png", "label": "右侧视角"}],
    }

    items = build_storyboard_reference_items(
        prompt_json=prompt_json,
        characters=characters,
        location=location,
    )

    assert [item["url"] for item in items] == [
        "/upload/character/milkshake.png",
        "/upload/location/hall.png",
    ]
    assert all("variant_label" not in item for item in items)


def test_reference_selection_keeps_legacy_url_only_asset_fallback():
    prompt_json = {"scene_desc": "【【奶昔】】站在大厅。"}
    characters = [{"id": 4, "name": "奶昔", "url": "/upload/character/legacy.png"}]

    items = build_storyboard_reference_items(
        prompt_json=prompt_json,
        characters=characters,
        location=None,
    )

    assert items[0]["url"] == "/upload/character/legacy.png"


def test_storyboard_image_skill_requires_reference_legend_and_prompt_matched_assets():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    skill_paths = [
        root / "script_writer_core" / "skills" / "storyboard-image" / "SKILL.md",
        root / "agents" / "skills" / "storyboard-image" / "SKILL.md",
    ]
    for path in skill_paths:
        content = path.read_text(encoding="utf-8")
        assert "参考图说明" in content
        assert "edit_image.prompt" in content
        assert "不要加入未出现在当前画面提示词或视频提示词中的角色/道具参考图" in content
