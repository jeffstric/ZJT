from pathlib import Path
import sys
import asyncio
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api import storyboard as storyboard_api


def test_auto_submit_dialogue_voiceovers_submits_and_skips(monkeypatch):
    constants = storyboard_api.StoryboardAudioGenerateConstants
    scenes = [
        {
            "id": 10,
            "dialogues": [
                {"id": 101, "scene_id": 10, "text": "hello", "character_id": 1},
                {"id": 102, "scene_id": 10, "text": "", "character_id": 1},
                {"id": 103, "scene_id": 10, "text": "旁白", "character_id": None},
                {"id": 104, "scene_id": 10, "text": "missing voice", "character_id": 2},
            ],
        }
    ]
    dialogues = {
        101: SimpleNamespace(id=101, scene_id=10, text="hello", character_id=1, selected_audio_id=None),
        102: SimpleNamespace(id=102, scene_id=10, text="", character_id=1, selected_audio_id=None),
        103: SimpleNamespace(id=103, scene_id=10, text="旁白", character_id=None, selected_audio_id=None),
        104: SimpleNamespace(id=104, scene_id=10, text="missing voice", character_id=2, selected_audio_id=None),
    }
    characters = {
        1: SimpleNamespace(id=1, default_voice="/upload/voice/a.wav"),
        2: SimpleNamespace(id=2, default_voice=""),
    }
    created_audio = []
    created_tasks = []
    created_dialogue_audio = []
    selected = []

    monkeypatch.setattr(storyboard_api.StoryboardDialogueModel, "get_by_id", lambda dialogue_id: dialogues[dialogue_id])
    monkeypatch.setattr(storyboard_api.CharacterModel, "get_by_id", lambda character_id: characters[character_id])
    monkeypatch.setattr(
        storyboard_api.AIAudioModel,
        "create",
        lambda **kwargs: created_audio.append(kwargs) or 501,
    )
    monkeypatch.setattr(
        storyboard_api.TasksModel,
        "create",
        lambda **kwargs: created_tasks.append(kwargs) or 1,
    )
    monkeypatch.setattr(
        storyboard_api.StoryboardDialogueAudioModel,
        "create",
        lambda **kwargs: created_dialogue_audio.append(kwargs) or 301,
    )
    monkeypatch.setattr(
        storyboard_api.StoryboardDialogueAudioModel,
        "set_selected",
        lambda dialogue_id, dialogue_audio_id: selected.append((dialogue_id, dialogue_audio_id)) or 1,
    )

    result = asyncio.run(storyboard_api._auto_submit_storyboard_dialogue_voiceovers(scenes, user_id=7))

    assert result["enabled"] is True
    assert result["submitted_count"] == 1
    assert result["skipped_count"] == 3
    assert result["submitted"][0]["dialogue_id"] == 101
    assert result["submitted"][0]["audio_id"] == 501
    assert created_audio[0]["text"] == "hello"
    assert created_audio[0]["ref_path"] == "/upload/voice/a.wav"
    assert created_dialogue_audio == [{"dialogue_id": 101, "ai_audio_id": 501}]
    assert selected == [(101, 301)]
    reasons = {item["dialogue_id"]: item["reason"] for item in result["skipped"]}
    assert reasons[102] == constants.SKIP_REASON_EMPTY_TEXT
    assert reasons[103] == constants.SKIP_REASON_NARRATION_WITHOUT_VOICE
    assert reasons[104] == constants.SKIP_REASON_MISSING_REFERENCE_AUDIO


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
    auto_missing_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "auto_missing_images.js").read_text(encoding="utf-8")
    state_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "state.js").read_text(encoding="utf-8")

    assert "maybePromptGenerateFromScript" in bootstrap_js
    assert "generateFromScript" in api_js
    assert "autoGenerateMissingFirstFrames" in auto_missing_js
    assert "limit: missing.length" in auto_missing_js
    assert "sequence_mode: state.autoImageSequenceMode" in auto_missing_js
    assert "autoImageSequenceMode: 'balanced'" in state_js
    assert "autoImageSequenceMode: state.autoImageSequenceMode" in state_js
    assert 'data-action="set-auto-image-sequence-mode"' in render_js
    assert 'data-auto-image-sequence-mode="speed"' in render_js
    assert 'data-auto-image-sequence-mode="balanced"' in render_js
    assert 'data-auto-image-sequence-mode="quality"' in render_js
    assert "showGenerateFromScriptDialog" in render_js
    assert 'data-config-select="scriptSplit"' in render_js
    assert "generate-from-script-confirm" in events_js
    assert "set-auto-image-sequence-mode" in events_js
    assert "state.autoImageSequenceMode = mode;" in events_js
    assert "resolveSelectedScriptSplitLlmModel" in events_js
    assert "model_id: splitModel.model_id" in events_js
    assert "vendor_id: splitModel.vendor_id" in events_js
    assert "import { autoGenerateMissingFirstFrames } from './auto_missing_images.js';" in events_js
    assert "autoGenerateMissingFirstFrames();" in events_js
    assert events_js.index("loadStoryboardData(response);") < events_js.index("autoGenerateMissingFirstFrames();")


def test_scene_task_status_falls_back_to_ai_audio_result_url():
    storyboard_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")

    assert "if not item['audio_url'] and aa.result_url" in storyboard_py
    assert "item['audio_url'] = aa.result_url" in storyboard_py


def test_storyboard_frontend_polls_auto_dialogue_audio_after_split():
    events_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "events.js").read_text(encoding="utf-8")

    assert "function handleAutoDialogueAudioPolling(response)" in events_js
    assert "response.audio_auto_generate" in events_js
    assert "pollSceneTaskStatus(sceneId);" in events_js
    assert "条配音任务" in events_js
    assert events_js.index("loadStoryboardData(response);") < events_js.index("handleAutoDialogueAudioPolling(response);")
