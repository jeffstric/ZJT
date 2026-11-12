from llm.script_parser import sanitize_dialogue_text_tokens


def test_strips_character_tokens_inside_dialogue_text():
    parsed = {
        "shot_groups": [
            {
                "shots": [
                    {
                        "shot_id": "s001",
                        "dialogue": [
                            {
                                "character_id": "char_001",
                                "character_name": "【【赵志高】】",
                                "text": "【【小李】】，你给我站住！",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    result = sanitize_dialogue_text_tokens(parsed)

    item = result["shot_groups"][0]["shots"][0]["dialogue"][0]
    # 台词内的【【】】标记被剥离为纯文本名字
    assert item["text"] == "小李，你给我站住！"
    # 说话人字段（character_name）不受影响
    assert item["character_name"] == "【【赵志高】】"


def test_keeps_visual_fields_and_plain_dialogue_untouched():
    parsed = {
        "shot_groups": [
            {
                "shots": [
                    {
                        "shot_id": "s001",
                        "opening_frame_description": "【【赵志高】】站在仓库门口，怒视前方。",
                        "scene_detail": "【【赵志高】】伸手拦住去路。",
                        "dialogue": [
                            {"character_name": "【【赵志高】】", "text": "小李，你给我站住！"},
                        ],
                    }
                ],
            }
        ]
    }

    result = sanitize_dialogue_text_tokens(parsed)

    shot = result["shot_groups"][0]["shots"][0]
    # 画面/动作描写字段中的角色标记必须保留（真正在场角色）
    assert "【【赵志高】】" in shot["opening_frame_description"]
    assert "【【赵志高】】" in shot["scene_detail"]
    assert shot["dialogue"][0]["text"] == "小李，你给我站住！"


def test_handles_dialogues_key_and_dict_and_malformed_items():
    parsed = {
        "shot_groups": [
            {
                "shots": [
                    {
                        "shot_id": "s001",
                        "dialogues": [
                            {"text": "把【【 公文包 】】递给我"},
                            "not-a-dict",
                            {"text": ""},
                        ],
                        "dialogue": {"text": "听说【【布冯】】也来了"},
                    }
                ],
            },
            "not-a-group",
        ]
    }

    result = sanitize_dialogue_text_tokens(parsed)

    shot = result["shot_groups"][0]["shots"][0]
    assert shot["dialogues"][0]["text"] == "把公文包递给我"
    assert shot["dialogues"][2] == {"text": ""}
    # dict 形式的 dialogue 同样被处理
    assert shot["dialogue"]["text"] == "听说布冯也来了"
