from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api import storyboard as storyboard_api


def test_build_scenes_from_parsed_script_creates_scene_and_dialogue_payloads():
    parsed = {
        "characters": [
            {"id": "char_001", "name": "小林", "character_db_id": 17},
            {"id": "char_002", "name": "旁白", "character_db_id": None},
        ],
        "locations": [
            {"id": "loc_001", "name": "客厅", "location_db_id": 23},
        ],
        "shot_groups": [
            {
                "group_id": "grp_001",
                "group_name": "场景编号：A1 客厅 夜晚",
                "group_type": "因果组",
                "shots": [
                    {
                        "shot_id": "s001",
                        "shot_number": 1,
                        "duration": 6,
                        "location_id": "loc_001",
                        "location_name": "客厅",
                        "camera_angle": "平视",
                        "shot_type": "中景",
                        "camera_movement": "推进",
                        "description": "【【小林】】把钥匙放在桌上",
                        "opening_frame_description": "【【小林】】站在客厅桌边，钥匙在桌面中央。",
                        "scene_detail": "镜头推进到桌面钥匙。",
                        "action": "【【小林】】松开手。",
                        "narrative_purpose": "揭示：通过钥匙特写说明角色已回家",
                        "dialogue": [
                            {
                                "character_id": "char_001",
                                "text": "我回来了。",
                            },
                            {
                                "character_id": "char_002",
                                "text": "夜色压低了房间里的声音。",
                            },
                        ],
                    }
                ],
            }
        ],
    }

    scenes = storyboard_api.build_storyboard_scenes_from_parsed_script(parsed, style="写实电影")

    assert len(scenes) == 1
    scene = scenes[0]
    assert scene["title"] == "分镜1"
    assert scene["duration"] == 6
    assert scene["video_type"] == "video"
    assert scene["prompt"]["style"] == "写实电影"
    assert scene["prompt"]["perspective"] == "平视 / 中景"
    assert scene["prompt"]["scene_desc"] == "【【小林】】站在客厅桌边，钥匙在桌面中央。\n镜头推进到桌面钥匙。"
    assert scene["prompt"]["source"]["group_name"] == "场景编号：A1 客厅 夜晚"
    assert scene["prompt"]["source"]["location_db_id"] == 23
    assert "揭示：通过钥匙特写说明角色已回家" in scene["video_prompt"]
    assert scene["dialogues"] == [
        {"character_id": 17, "text": "我回来了。", "speed": 1.0, "volume": 100},
        {"character_id": None, "text": "夜色压低了房间里的声音。", "speed": 1.0, "volume": 100},
    ]


def test_storyboard_frontend_exposes_generate_from_script_flow():
    bootstrap_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "bootstrap.js").read_text(encoding="utf-8")
    api_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "api.js").read_text(encoding="utf-8")
    render_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "render.js").read_text(encoding="utf-8")
    events_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "events.js").read_text(encoding="utf-8")

    assert "maybePromptGenerateFromScript" in bootstrap_js
    assert "generateFromScript" in api_js
    assert "showGenerateFromScriptDialog" in render_js
    assert "generate-from-script-confirm" in events_js
