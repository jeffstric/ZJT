from services.storyboard_reference_prompt_service import (
    append_reference_legend,
    append_storyboard_visual_suffix,
    append_voice_casting_note,
    append_voice_reference_note,
    build_reference_legend,
    build_storyboard_reference_items,
    build_voice_casting_note,
    collect_character_voice_references,
    extract_speaking_character_ids,
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


def test_multiline_visual_suffix_is_idempotent_and_removable():
    style = "皮克斯3D动画\r\n高品质建模\n柔和电影光照"
    composition = "三分法构图\r动态平衡"

    once = append_storyboard_visual_suffix(
        "镜头内容\n参考图说明：图1是场景。",
        style=style,
        composition_preference=composition,
    )
    repeated = append_storyboard_visual_suffix(
        once,
        style=style,
        composition_preference=composition,
    )

    assert repeated == once
    assert repeated.count("图片风格：") == 1
    assert repeated.count("构图倾向：") == 1
    assert "图片风格：皮克斯3D动画\n高品质建模\n柔和电影光照" in repeated
    assert "构图倾向：三分法构图\n动态平衡" in repeated
    assert remove_storyboard_visual_suffix(
        repeated,
        style=style,
        composition_preference=composition,
    ) == "镜头内容\n参考图说明：图1是场景。"


def test_multiline_visual_suffix_removal_keeps_similar_body_lines():
    prompt = (
        "镜头正文包含高品质建模，但不是后缀块。\n"
        "高品质建模\n\n"
        "图片风格：皮克斯3D动画\n高品质建模\n"
        "构图倾向：三分法构图\n动态平衡"
    )

    cleaned = remove_storyboard_visual_suffix(
        prompt,
        style="皮克斯3D动画\n高品质建模",
        composition_preference="三分法构图\n动态平衡",
    )

    assert cleaned == "镜头正文包含高品质建模，但不是后缀块。\n高品质建模"


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


def test_reference_items_include_user_added_second_character_tag():
    """用户后在提示词新增【【角色】】时，只要库记录在 characters 列表中就会挂上参考图。"""
    prompt_json = {
        "scene_desc": "【【德保罗】】与【【梅西】】并肩站在镜头前。",
        "character_desc": "德保罗",  # 拆分时可能只有一人；不应阻止第二人标记
    }
    characters = [
        {"id": 1, "name": "德保罗", "reference_image": "/upload/character/depaul.png"},
        {"id": 2, "name": "梅西", "reference_image": "/upload/character/messi.png"},
    ]

    items = build_storyboard_reference_items(
        prompt_json=prompt_json,
        characters=characters,
        location=None,
    )

    assert [(item["type"], item["name"]) for item in items] == [
        ("角色", "德保罗"),
        ("角色", "梅西"),
    ]
    assert [item["url"] for item in items] == [
        "/upload/character/depaul.png",
        "/upload/character/messi.png",
    ]


def test_reference_items_ignore_dialogue_only_character_without_tag():
    """仅对白/character_desc 有角色、提示词未【【】】标记时，不进参考图。"""
    prompt_json = {
        "scene_desc": "【【德保罗】】独自站在街角。",
        "character_desc": "德保罗、梅西",
    }
    characters = [
        {"id": 1, "name": "德保罗", "reference_image": "/upload/character/depaul.png"},
        {"id": 2, "name": "梅西", "reference_image": "/upload/character/messi.png"},
    ]

    items = build_storyboard_reference_items(
        prompt_json=prompt_json,
        characters=characters,
        location=None,
    )

    assert [(item["type"], item["name"]) for item in items] == [("角色", "德保罗")]


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


# ── 角色音色参考注入（supports_voice_input 门控）─────────────────────────────

VOICE_CHARACTERS = [
    {"name": "林悦", "default_voice": "/upload/character/voice/linyue.wav"},
    {"name": "张三", "default_voice": "/upload/character/voice/zhangsan.wav"},
    {"name": "无音色角色", "default_voice": ""},
    {"name": "王五", "default_voice": "/upload/character/voice/wangwu.wav"},
]


def test_extract_speaking_character_ids():
    """说话角色 = 对话记录里 text 非空的角色；text 空或无 character_id 不算。"""
    dialogues = [
        {"character_id": 42, "text": "李保国！你看看你扫的什么地！"},
        {"character_id": 43, "text": ""},          # 占位/已清空，不开口
        {"character_id": None, "text": "旁白"},     # 未绑定角色
        {"character_id": "44", "text": "知道了"},   # 字符串 id 也接受
        "not-a-dict",
    ]
    assert extract_speaking_character_ids(dialogues) == {42, 44}
    assert extract_speaking_character_ids(None) == set()
    assert extract_speaking_character_ids([]) == set()


def test_voice_references_filtered_by_speaking_characters():
    """H3 单人/少人说话镜头只注入开口说话角色的音色；None 不过滤（seedance 现状）。"""
    characters = [
        {"id": 1, "name": "赵志高", "default_voice": "/upload/character/voice/zhao.wav"},
        {"id": 2, "name": "李卫国", "default_voice": "/upload/character/voice/li.wav"},
    ]
    # 只有赵志高说话：只注入他的音色（分镜 2 事故修复：第二路不挂槽）
    items, note = collect_character_voice_references(
        supports_voice_input=True,
        characters=characters,
        image_mode="multi_reference",
        speaking_character_ids={1},
    )
    assert [item["name"] for item in items] == ["赵志高"]
    assert note == "参考音频说明：音频1是角色：赵志高的音色样本，角色说话时请保持相同音色。"

    # 两人都说话：都注入
    both, _ = collect_character_voice_references(
        supports_voice_input=True,
        characters=characters,
        image_mode="multi_reference",
        speaking_character_ids={1, 2},
    )
    assert [item["name"] for item in both] == ["赵志高", "李卫国"]

    # None = 不过滤（现行为，seedance 等链路）
    unfiltered, _ = collect_character_voice_references(
        supports_voice_input=True,
        characters=characters,
        image_mode="multi_reference",
        speaking_character_ids=None,
    )
    assert [item["name"] for item in unfiltered] == ["赵志高", "李卫国"]

    # 空集合：一个都不注入（有对话记录但角色不在库等边界）
    empty, empty_note = collect_character_voice_references(
        supports_voice_input=True,
        characters=characters,
        image_mode="multi_reference",
        speaking_character_ids=set(),
    )
    assert empty == [] and empty_note == ""


def test_voice_references_collected_when_model_supports():
    items, note = collect_character_voice_references(
        supports_voice_input=True,
        characters=VOICE_CHARACTERS,
        image_mode="multi_reference",
    )

    # 截断到 MAX_VOICE_REFERENCE_AUDIOS=2，无音色角色跳过
    assert [item["name"] for item in items] == ["林悦", "张三"]
    assert note == (
        "参考音频说明：音频1是角色：林悦的音色样本，"
        "音频2是角色：张三的音色样本，角色说话时请保持相同音色。"
    )


def test_voice_references_skipped_for_unsupported_model_or_mode():
    assert collect_character_voice_references(
        supports_voice_input=False,
        characters=VOICE_CHARACTERS,
        image_mode="multi_reference",
    ) == ([], "")
    assert collect_character_voice_references(
        supports_voice_input=True,
        characters=VOICE_CHARACTERS,
        image_mode="first_last_frame",
    ) == ([], "")
    assert collect_character_voice_references(
        supports_voice_input=True,
        characters=VOICE_CHARACTERS,
        image_mode="first_last_with_ref",
    ) == ([], "")


def test_voice_references_dedupe_against_existing_audio_and_offset_index():
    items, note = collect_character_voice_references(
        supports_voice_input=True,
        characters=VOICE_CHARACTERS,
        image_mode="multi_reference",
        existing_audio_urls="http://x/voice.wav, /upload/character/voice/linyue.wav",
    )

    # 与用户已携带音频同 URL 的角色音色去重；序号对齐最终合并列表位置（2 条已有 → 从 3 起）
    assert [item["url"] for item in items] == [
        "/upload/character/voice/zhangsan.wav",
        "/upload/character/voice/wangwu.wav",
    ]
    assert "音频3是角色：张三的音色样本" in note
    assert "音频4是角色：王五的音色样本" in note


def test_append_voice_reference_note_is_idempotent():
    _, note = collect_character_voice_references(
        supports_voice_input=True,
        characters=VOICE_CHARACTERS[:1],
        image_mode="multi_reference",
    )
    prompt = append_voice_reference_note("镜头内容", [{"name": "林悦", "url": "u"}])
    assert prompt.endswith(note)
    assert append_voice_reference_note(prompt, [{"name": "林悦", "url": "u"}]) == prompt


VOICE_DESC_CHARACTERS = [
    {"name": "林悦", "voice_desc": "25岁左右的年轻女性，声音清脆圆润，音量轻柔，语速轻快"},
    {"name": "张三"},
    {"name": "王五", "voice_desc": "  "},
]


def test_voice_casting_note_lists_only_characters_with_fingerprint():
    note = build_voice_casting_note(VOICE_DESC_CHARACTERS)
    assert note.startswith("角色音色说明：")
    assert "林悦的音色特征：25岁左右的年轻女性" in note
    assert "张三" not in note and "王五" not in note
    assert note.endswith("。描述这些角色说话的声音时必须遵循对应音色特征。")


def test_voice_casting_note_empty_without_fingerprints():
    assert build_voice_casting_note(VOICE_CHARACTERS) == ""
    assert build_voice_casting_note(None) == ""


def test_append_voice_casting_note_is_idempotent_and_skips_empty():
    note = build_voice_casting_note(VOICE_DESC_CHARACTERS)
    prompt = append_voice_casting_note("镜头内容", note)
    assert prompt.endswith(note)
    assert append_voice_casting_note(prompt, note) == prompt
    assert append_voice_casting_note("镜头内容", "") == "镜头内容"


def test_voice_reference_capability_flag_wired_on_expected_models_only():
    from config.unified_config import UnifiedConfigRegistry

    expected = {
        "minimax_h3_r2v",
        "minimax_h3_kfr",
        "seedance_2_0_fast",
        "seedance_2_0",
        "seedance_2_0_mini",
        "seedance_2_5",
    }
    enabled = {
        config.short_key or config.key
        for config in UnifiedConfigRegistry.get_all()
        if getattr(config, "supports_voice_input", False)
    }
    assert enabled == expected

    # 前端下发同步携带能力位
    grok = next(
        config for config in UnifiedConfigRegistry.get_all() if "grok" in config.key
    )
    assert grok.to_frontend_dict()["supports_voice_input"] is False
