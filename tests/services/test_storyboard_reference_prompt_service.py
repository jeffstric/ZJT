from services.storyboard_reference_prompt_service import (
    append_reference_legend,
    build_storyboard_reference_items,
)


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
