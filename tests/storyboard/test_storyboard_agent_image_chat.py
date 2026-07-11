from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_storyboard_image_skill_exists_and_uses_image_generation_tools():
    skill_path = PROJECT_ROOT / "agents" / "skills" / "storyboard-image" / "SKILL.md"

    assert skill_path.exists()
    content = skill_path.read_text(encoding="utf-8")
    assert "generate_text_to_image" in content
    assert "edit_image" in content
    assert "project_ids" in content
    assert "当前分镜" in content


def test_storyboard_agent_image_backend_routes_exist():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")

    assert "@router.post('/scene/{scene_id}/ai-chat')" in api_py
    assert "@router.get('/agent-task/{task_id}/stream')" in api_py
    assert "@router.post('/scene/{scene_id}/bind-agent-image-task')" in api_py
    assert "StoryboardSceneAssetModel.create" in api_py
    assert "image_task_submitted" in api_py


def test_storyboard_image_agent_uses_task_model_id_for_llm_model_name():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")

    assert "_resolve_storyboard_agent_model" in api_py
    assert "ModelModel.get_by_id(int(model_id))" in api_py
    assert "model = self._resolve_storyboard_agent_model(" in api_py


def test_storyboard_agent_auth_token_is_normalized_before_task_storage():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")

    assert "token.lower().startswith('bearer ')" in api_py
    assert "token = token[7:].strip()" in api_py
    assert "auth_token=token" in api_py


def test_storyboard_agent_chat_history_uses_scene_scoped_chat_messages():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")

    assert "_storyboard_scene_chat_session_id" in api_py
    assert "_record_storyboard_agent_message" in api_py
    assert "_list_storyboard_agent_messages" in api_py
    assert "ChatMessagesModel.create" in api_py
    assert "@router.get('/scene/{scene_id}/ai-chat/history')" in api_py


def test_storyboard_agent_image_frontend_flow_exists():
    api_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "api.js").read_text(encoding="utf-8")
    events_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "events.js").read_text(encoding="utf-8")
    render_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "render.js").read_text(encoding="utf-8")
    state_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "state.js").read_text(encoding="utf-8")

    assert "startSceneAgentChat" in api_js
    assert "streamStoryboardAgentTask" in api_js
    assert "fetchSceneAgentChatHistory" in api_js
    assert "bindAgentImageTask" in api_js
    assert "sendStoryboardAgentMessage" in events_js
    assert "loadSceneAgentMessages" in events_js
    assert "image_task_submitted" in events_js
    assert "agentMessages" in render_js
    assert "agentMessages" in state_js
    assert "['image', '图片生成']" not in render_js
    assert "generation_target: state.chatMode === 'video' ? 'video' : 'image'" in events_js
    assert "api.generateSceneImage" not in events_js
    assert "api.generateSceneVideo" not in events_js


def test_storyboard_agent_video_mode_reaches_backend_prompt():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")
    skill_path = PROJECT_ROOT / "agents" / "skills" / "storyboard-image" / "SKILL.md"
    skill_content = skill_path.read_text(encoding="utf-8")

    assert "generation_target" in api_py
    assert "generation_target == 'video'" in api_py
    assert "本次目标是生成视频" in api_py
    assert "generate_text_to_video" in skill_content
    assert "image_to_video" in skill_content


def test_storyboard_agent_prompt_includes_reference_legend_constraints():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")

    assert "build_reference_legend" in api_py
    assert "【参考图说明】" in api_py
    assert "edit_image.prompt" in api_py
    assert "不要加入未出现在当前画面提示词或视频提示词中的角色/道具参考图" in api_py


def test_storyboard_scene_asset_candidates_enrich_result_url_from_ai_tool(monkeypatch):
    from api import storyboard as storyboard_api

    class FakeTool:
        result_url = "https://cdn.example.com/storyboard/frame.png"
        status = 2
        message = "done"
        project_id = "project-1"
        image_path = "https://cdn.example.com/a.png,https://cdn.example.com/b.png"

    monkeypatch.setattr(storyboard_api.AIToolsModel, "get_by_id", lambda record_id: FakeTool())

    assets = storyboard_api._enrich_scene_asset_result_urls([
        {
            "id": 5,
            "scene_id": 10,
            "asset_type": "first_frame",
            "ai_tool_id": 101,
            "result_url": "",
        }
    ])

    assert assets[0]["result_url"] == "https://cdn.example.com/storyboard/frame.png"
    assert assets[0]["status"] == 2
    assert assets[0]["message"] == "done"
    assert assets[0]["project_id"] == "project-1"


def test_storyboard_scene_asset_enrich_ignores_image_path_while_generating(monkeypatch):
    """生成中 image_path 是输入参考图，不能当作候选 result_url。"""
    from api import storyboard as storyboard_api

    class FakeTool:
        result_url = None
        status = 1  # PROCESSING
        message = None
        project_id = "project-running"
        image_path = (
            "http://localhost:9003/upload/cache/a.png,"
            "http://localhost:9003/upload/character/pic/b.png,"
            "http://localhost:9003/upload/location/pic/c.png"
        )
        video_path = None

    monkeypatch.setattr(storyboard_api.AIToolsModel, "get_by_id", lambda record_id: FakeTool())

    assets = storyboard_api._enrich_scene_asset_result_urls([
        {
            "id": 389,
            "scene_id": 10,
            "asset_type": "first_frame",
            "ai_tool_id": 202,
            "result_url": None,
        }
    ])

    assert not assets[0].get("result_url")
    assert assets[0]["status"] == 1
    assert assets[0]["project_id"] == "project-running"


def test_storyboard_scene_asset_list_enrichment_runs_off_event_loop():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")

    assert "await asyncio.to_thread(_enrich_scene_asset_result_urls, assets)" in api_py


def test_storyboard_scene_asset_enrich_does_not_fallback_to_image_path():
    """候选 URL 补全只能用 result_url，不能回退 image_path（输入参考图）。"""
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")
    # 在 _enrich_scene_asset_result_urls 函数体内不应再把 image_path 当作 result_url
    start = api_py.find("def _enrich_scene_asset_result_urls")
    assert start > 0
    end = api_py.find("\ndef ", start + 1)
    body = api_py[start:end if end > 0 else None]
    assert "tool_info.get('result_url')" in body
    assert "tool_info.get('image_path')" not in body
    assert "getattr(tool, 'image_path'" not in body


def test_storyboard_candidate_loading_placeholder_in_frontend():
    render_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "render.js").read_text(encoding="utf-8")
    assert "renderCandidatePlaceholder" in render_js
    assert "isRenderableCandidateUrl" in render_js
    assert "candidate-loading" in render_js
    assert "includes(',')" in render_js


def test_storyboard_dialogue_model_selection_distinguishes_same_model_across_vendors():
    render_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "render.js").read_text(encoding="utf-8")

    assert "isSelectedDialogueModel" in render_js
    assert "selected.model_id" in render_js
    assert "selected.vendor_id" in render_js
