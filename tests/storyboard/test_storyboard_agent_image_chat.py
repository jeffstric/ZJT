import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace


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


def test_storyboard_image_skill_copies_define_spatial_and_neighbor_rules():
    skill_paths = [
        PROJECT_ROOT / "agents" / "skills" / "storyboard-image" / "SKILL.md",
        PROJECT_ROOT / "script_writer_core" / "skills" / "storyboard-image" / "SKILL.md",
    ]

    for skill_path in skill_paths:
        content = skill_path.read_text(encoding="utf-8")
        assert "当前分镜空间硬约束" in content
        assert "物理锚点、容器槽位和三维位置" in content
        assert "offscreen、occluded" in content
        assert "相邻分镜不能覆盖当前镜头" in content
        assert "禁止提前复制后一分镜" in content


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


def test_storyboard_image_agent_enforces_style_and_composition_at_tool_boundary():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")

    assert "StoryboardAgentImageToolExecutor" in api_py
    assert "style=getattr(sb, 'style', '') if sb else ''" in api_py
    assert "composition_preference=getattr(sb, 'composition_preference', '') if sb else ''" in api_py
    assert "style=self.style" in api_py
    assert "composition_preference=self.composition_preference" in api_py


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


def test_storyboard_agent_task_reuses_short_scene_session_id():
    """后台任务必须复用分镜会话，不能构造超过 chat_messages VARCHAR(36) 的随机 ID。"""
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")
    route_start = api_py.index("@router.post('/scene/{scene_id}/ai-chat')")
    route_end = api_py.index("@router.get('/scene/{scene_id}/ai-chat/history')", route_start)
    route_body = api_py[route_start:route_end]

    assert "session_id = _storyboard_scene_chat_session_id(scene_id)" in route_body
    assert 'session_id = f"storyboard-{scene_id}-{uuid.uuid4()}"' not in route_body
    assert len("storyboard-scene-2147483647") <= 36


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
    assert "generation_target: isVideo ? 'video' : 'image'" in events_js
    assert "api.generateSceneImage" not in events_js
    assert "api.generateSceneVideo" not in events_js


def test_storyboard_agent_running_state_is_isolated_by_scene():
    """一个分镜的 Agent 任务不能禁用其他分镜的对话框或把流消息串过去。"""
    events_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "events.js").read_text(encoding="utf-8")
    render_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "render.js").read_text(encoding="utf-8")
    state_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "state.js").read_text(encoding="utf-8")

    assert "agentRunsBySceneId" in state_js
    assert "isSceneAgentRunning" in state_js
    assert "startSceneAgentRun" in state_js
    assert "finishSceneAgentRun" in state_js
    assert "appendSceneAgentMessage" in state_js
    assert "activateSceneAgentMessages" in state_js

    assert "isSceneAgentRunning(currentScene?.id)" in render_js
    assert "state.isAgentRunning" not in render_js

    assert "const streamSceneId = current.id" in events_js
    assert "appendSceneAgentMessage(sceneId" in events_js
    assert "pushAgentMessageForScene(streamSceneId" in events_js
    assert "finishSceneAgentRun(streamSceneId" in events_js
    assert "activateSceneAgentMessages(sceneId)" in events_js
    assert "rerenderAgentPanelForScene(streamSceneId)" in events_js


def test_storyboard_agent_video_mode_reaches_backend_prompt():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")
    skill_path = PROJECT_ROOT / "agents" / "skills" / "storyboard-image" / "SKILL.md"
    skill_content = skill_path.read_text(encoding="utf-8")

    assert "generation_target" in api_py
    assert "generation_target == 'video'" in api_py
    assert "本次目标是生成视频" in api_py
    assert "generate_text_to_video" in skill_content
    assert "image_to_video" in skill_content


def test_storyboard_video_preferences_do_not_read_marketing_preferences():
    from api import storyboard as storyboard_api

    preferences = asyncio.run(
        storyboard_api._build_storyboard_agent_video_preferences(
            user_id=7,
            world_id=9,
            storyboard=SimpleNamespace(workflow_ratio="9:16"),
            image_mode="first_last_frame",
            duration_seconds=8,
            video_resolution="1080p",
        )
    )

    assert preferences == {
        "ratio": "9:16",
        "image_mode": "first_last_frame",
        "duration": 8,
        "resolution": "1080p",
    }


def test_storyboard_agent_submission_does_not_write_legacy_marketing_model_preferences():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")
    route_start = api_py.index("@router.post('/scene/{scene_id}/ai-chat')")
    route_end = api_py.index("@router.get('/scene/{scene_id}/ai-chat/history')", route_start)
    route_body = api_py[route_start:route_end]

    assert "set_text_to_image_model_id" not in route_body
    assert "set_text_to_video_model_id" not in route_body
    assert "set_image_to_video_model_id" not in route_body


def test_storyboard_direct_generation_uses_storyboard_preference_surface():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")
    image_route_start = api_py.index("@router.post('/scene/{scene_id}/generate-image')")
    image_route_end = api_py.index("@router.post('/scene/{scene_id}/generate-video')", image_route_start)
    image_route = api_py[image_route_start:image_route_end]
    video_route_end = api_py.index("@router.post('/dialogue/{dialogue_id}/generate-voiceover')", image_route_end)
    video_route = api_py[image_route_end:video_route_end]

    assert "preference_surface=MediaGenerationSurface.STORYBOARD_UI" in image_route
    assert "set_text_to_image_model_id" not in image_route
    assert "_resolve_storyboard_generation_snapshot_sync" in video_route
    assert "'generation_snapshot': generation_snapshot" in video_route


def test_storyboard_agent_prompt_includes_reference_legend_constraints():
    api_py = (PROJECT_ROOT / "api" / "storyboard.py").read_text(encoding="utf-8")

    assert "build_reference_legend" in api_py
    assert "【参考图说明】" in api_py
    assert "edit_image.prompt" in api_py
    assert "不要加入未出现在当前画面提示词或视频提示词中的角色/道具参考图" in api_py


def test_storyboard_agent_builds_explicit_spatial_constraints():
    from api import storyboard as storyboard_api

    prompt_json = {
        "spatial_world": {
            "space_units": [
                {"space_unit_id": "car_cabin", "name": "泡泡蒸汽车驾驶室"},
                {"space_unit_id": "forest", "name": "迷雾森林"},
            ]
        },
        "spatial_layout": {
            "space_unit_refs": ["car_cabin"],
            "camera_pose": {
                "space_unit_id": "car_cabin",
                "eye": [0, -2, 1.4],
                "target": [0, 1, 1.2],
                "up": [0, 0, 1],
                "fov": 50,
            },
            "camera_anchor": {
                "camera_position": "后排中央",
                "view_direction": "rear_to_front",
                "screen_axis_mapping": {"vehicle_left": "screen_left"},
            },
            "containers": [{
                "container_id": "car",
                "name": "泡泡蒸汽车",
                "slots": [
                    {
                        "slot": "驾驶座",
                        "character_id": "char_001",
                        "name": "奶昔_Milkshake",
                        "visibility": "visible",
                        "framing_role": "primary_subject",
                    },
                    {
                        "slot": "副驾驶座",
                        "character_id": "char_002",
                        "name": "奶酪_Cheese",
                        "visibility": "offscreen",
                        "framing_role": "offscreen_continuity",
                    },
                ],
            }],
            "continuity": {
                "changed_positions": [],
                "notes": "角色仍在原座位",
            },
        },
    }

    constraints = storyboard_api._build_storyboard_spatial_constraints(prompt_json)

    assert constraints["space_unit_refs"] == ["car_cabin"]
    assert constraints["space_units"] == [
        {"space_unit_id": "car_cabin", "name": "泡泡蒸汽车驾驶室"}
    ]
    assert constraints["camera_pose"]["eye"] == [0, -2, 1.4]
    assert constraints["camera_anchor"]["view_direction"] == "rear_to_front"
    assert constraints["visible_entities"][0]["slot"] == "驾驶座"
    assert constraints["continuity_only_entities"][0]["slot"] == "副驾驶座"
    assert constraints["continuity"]["notes"] == "角色仍在原座位"


def test_storyboard_agent_spatial_constraints_reuse_shared_projection_engine(monkeypatch):
    from api import storyboard as storyboard_api

    calls = []

    def fake_build_spatial_prompt_context(spatial_layout, spatial_world):
        calls.append((spatial_layout, spatial_world))
        return {
            "camera_pose": {"eye": [0, -2, 1.4]},
            "visible_entities": [{
                "name": "奶昔",
                "slot": "驾驶座",
                "derived_screen_position": "screen_right",
                "visibility": "visible",
            }],
            "hidden_entities": [{
                "name": "奶酪",
                "slot": "副驾驶座",
                "derived_screen_position": "outside_frame_left",
                "visibility": "offscreen",
            }],
            "world_index": {},
        }

    monkeypatch.setattr(
        storyboard_api,
        "build_spatial_prompt_context",
        fake_build_spatial_prompt_context,
    )
    prompt_json = {
        "spatial_world": {"space_units": [{"space_unit_id": "car_cabin"}]},
        "spatial_layout": {
            "space_unit_refs": ["car_cabin"],
            "containers": [],
            "continuity": {},
        },
    }

    constraints = storyboard_api._build_storyboard_spatial_constraints(prompt_json)

    assert calls == [(prompt_json["spatial_layout"], prompt_json["spatial_world"])]
    assert constraints["visible_entities"][0]["derived_screen_position"] == "screen_right"
    assert constraints["continuity_only_entities"][0]["visibility"] == "offscreen"


def test_storyboard_agent_loads_only_immediate_valid_neighbor_frames(monkeypatch):
    from api import storyboard as storyboard_api

    scene = SimpleNamespace(id=20, storyboard_id=9)
    monkeypatch.setattr(
        storyboard_api.StoryboardSceneModel,
        "list_by_storyboard",
        lambda storyboard_id: [
            {
                "id": 10,
                "sort_order": 1,
                "title": "分镜1",
                "first_frame_url": "https://cdn.example.com/scene-10.png",
                "prompt_json": {"scene_desc": "森林入口"},
            },
            {
                "id": 20,
                "sort_order": 2,
                "title": "分镜2",
                "first_frame_url": "https://cdn.example.com/scene-20.png",
                "prompt_json": {"scene_desc": "当前镜头"},
            },
            {
                "id": 30,
                "sort_order": 3,
                "title": "分镜3",
                "first_frame_url": "https://cdn.example.com/a.png,https://cdn.example.com/b.png",
                "prompt_json": {"scene_desc": "无效多图结果"},
            },
            {
                "id": 40,
                "sort_order": 4,
                "title": "分镜4",
                "first_frame_url": "https://cdn.example.com/scene-40.png",
                "prompt_json": {"scene_desc": "更远镜头"},
            },
        ],
    )

    neighbors = storyboard_api._load_storyboard_agent_neighbors(scene)

    assert neighbors["previous"]["scene_id"] == 10
    assert neighbors["previous"]["first_frame_url"] == "https://cdn.example.com/scene-10.png"
    assert neighbors["previous"]["prompt_summary"] == "森林入口"
    assert neighbors["next"]["scene_id"] == 30
    assert neighbors["next"]["first_frame_url"] == ""
    assert 40 not in [item.get("scene_id") for item in neighbors.values() if item]


def test_storyboard_agent_appends_current_and_neighbor_frames_after_asset_references():
    from api import storyboard as storyboard_api
    from services.storyboard_reference_prompt_service import reference_urls

    items = [{
        "type": "角色",
        "name": "奶昔_Milkshake",
        "url": "https://cdn.example.com/milkshake.png",
    }]
    neighbors = {
        "previous": {
            "scene_id": 10,
            "title": "分镜1",
            "first_frame_url": "https://cdn.example.com/previous.png",
        },
        "next": {
            "scene_id": 30,
            "title": "分镜3",
            "first_frame_url": "",
        },
    }

    storyboard_api._append_storyboard_agent_frame_reference(
        items,
        "https://cdn.example.com/current.png",
        source_type="current_frame",
        title="分镜2",
    )
    storyboard_api._append_storyboard_agent_neighbor_references(items, neighbors)
    storyboard_api._append_storyboard_agent_frame_reference(
        items,
        "https://cdn.example.com/previous.png",
        source_type="previous_frame",
        title="重复前镜",
    )

    assert reference_urls(items) == [
        "https://cdn.example.com/milkshake.png",
        "https://cdn.example.com/current.png",
        "https://cdn.example.com/previous.png",
    ]
    assert [item["type"] for item in items] == [
        "角色",
        "当前分镜已有首帧",
        "前一分镜首帧",
    ]


def test_storyboard_agent_message_makes_spatial_and_neighbor_precedence_explicit():
    from api import storyboard as storyboard_api

    scene = SimpleNamespace(
        title="分镜2",
        duration=4,
        prompt_json={
            "scene_desc": "车内近景",
            "spatial_layout": {"space_unit_refs": ["car_cabin"]},
        },
    )
    storyboard = SimpleNamespace(
        style="动画电影",
        composition_preference="电影构图",
        workflow_ratio="16:9",
    )
    spatial_constraints = {
        "space_unit_refs": ["car_cabin"],
        "visible_entities": [{"name": "奶昔", "slot": "驾驶座", "visibility": "visible"}],
        "continuity_only_entities": [{"name": "奶酪", "slot": "副驾驶座", "visibility": "offscreen"}],
    }
    neighbor_contexts = {
        "previous": {
            "scene_id": 1,
            "direction": "previous",
            "first_frame_url": "https://cdn.example.com/previous.png",
            "prompt_summary": "车辆进入森林",
        },
        "next": {
            "scene_id": 3,
            "direction": "next",
            "first_frame_url": "https://cdn.example.com/next.png",
            "prompt_summary": "车辆驶出森林",
        },
    }

    message = storyboard_api._build_storyboard_agent_message(
        "重新生成首帧",
        scene,
        storyboard,
        reference_images=["https://cdn.example.com/previous.png"],
        reference_image_items=[{
            "type": "前一分镜首帧",
            "name": "分镜1",
            "url": "https://cdn.example.com/previous.png",
        }],
        spatial_constraints=spatial_constraints,
        neighbor_contexts=neighbor_contexts,
    )

    assert "【当前分镜空间硬约束】" in message
    assert '"slot": "驾驶座"' in message
    assert '"visibility": "offscreen"' in message
    assert "【相邻分镜连续性上下文】" in message
    assert "相邻分镜不能覆盖当前镜头的动作、机位、物理位置和可见实体" in message
    assert "offscreen、occluded 实体只能用于连续性推理，禁止写成当前画面可见主体" in message


def test_storyboard_agent_builds_image_reference_manifest_in_stable_order():
    from api import storyboard as storyboard_api

    images, items = storyboard_api._build_storyboard_agent_image_references(
        base_reference_images=[
            "https://cdn.example.com/character.png",
            "https://cdn.example.com/prop.png",
        ],
        base_reference_items=[
            {"type": "角色", "name": "奶昔", "url": "https://cdn.example.com/character.png"},
            {"type": "道具", "name": "汽车", "url": "https://cdn.example.com/prop.png"},
        ],
        current_first_frame_url="https://cdn.example.com/current.png",
        current_title="分镜2",
        neighbors={
            "previous": {
                "title": "分镜1",
                "first_frame_url": "https://cdn.example.com/previous.png",
            },
            "next": {
                "title": "分镜3",
                "first_frame_url": "https://cdn.example.com/next.png",
            },
        },
        user_reference_urls=[
            "https://cdn.example.com/character.png",
            "https://cdn.example.com/user.png",
        ],
    )

    assert images == [
        "https://cdn.example.com/character.png",
        "https://cdn.example.com/prop.png",
        "https://cdn.example.com/current.png",
        "https://cdn.example.com/previous.png",
        "https://cdn.example.com/next.png",
        "https://cdn.example.com/user.png",
    ]
    assert [item.get("source_type") for item in items[2:5]] == [
        "current_frame",
        "previous_frame",
        "next_frame",
    ]
    assert items[-1]["label"] == "用户上传参考图1"


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
