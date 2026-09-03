from pathlib import Path
from types import SimpleNamespace
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_video_tool_module():
    try:
        from services import storyboard_agent_video_tool
    except ImportError:
        return None
    return storyboard_agent_video_tool


def test_digital_human_scene_prompt_forces_scene_scoped_digital_human_tool():
    from api import storyboard as storyboard_api

    scene = SimpleNamespace(
        prompt_json={},
        title="分镜26",
        duration=5,
        video_type="digital_human",
    )
    storyboard = SimpleNamespace(
        style="写实",
        composition_preference="近景",
        workflow_ratio="16:9",
    )

    message = storyboard_api._build_storyboard_agent_message(
        "生成视频",
        scene,
        storyboard,
        generation_target="video",
        video_input_urls=["https://example.com/first-frame.png"],
        video_duration_seconds=5,
    )

    assert "必须调用 generate_digital_human" in message
    assert "不得调用 image_to_video" in message
    assert "系统会从当前分镜解析角色图和已完成的配音" in message


def test_digital_human_scene_only_exposes_digital_human_video_tool():
    module = _load_video_tool_module()
    assert module is not None

    allowed = module.resolve_storyboard_agent_allowed_tools(
        [
            "generate_text_to_image",
            "edit_image",
            "generate_text_to_video",
            "image_to_video",
            "get_user_computing_power",
            "ask_user",
        ],
        generation_target="video",
        video_type="digital_human",
    )

    assert "generate_digital_human" in allowed
    assert "image_to_video" not in allowed
    assert "generate_text_to_video" not in allowed
    assert "generate_text_to_image" not in allowed
    assert "edit_image" not in allowed
    assert "get_user_computing_power" in allowed


def test_storyboard_video_tool_uses_task_scoped_ratio_for_text_and_image_video(monkeypatch):
    module = _load_video_tool_module()
    assert module is not None

    from script_writer_core import mcp_tool

    monkeypatch.setattr(
        mcp_tool,
        "_get_video_preferences_func",
        lambda user_id, world_id: {"ratio": "16:9", "duration": 10},
    )
    delegated_calls = []

    class FakeDelegate:
        def get_tool_definitions(self, allowed_tools):
            return []

        def execute_tool(self, tool_name, tool_args, user_id, world_id, auth_token, **kwargs):
            delegated_calls.append({
                "tool_name": tool_name,
                "tool_args": dict(tool_args),
                "preferences": mcp_tool._get_video_preferences(user_id, world_id),
            })
            return {"success": True}

    scoped_preferences = {
        "ratio": "9:16",
        "duration": 5,
        "resolution": "720P",
        "image_mode": "first_last_frame",
        "task_id": 27,
        "model_name": "Grok",
    }
    executor = module.StoryboardAgentVideoToolExecutor(
        FakeDelegate(),
        scene_id=26,
        video_preferences=scoped_preferences,
    )

    executor.execute_tool(
        "generate_text_to_video",
        {"prompt": "camera moves", "ratio": "16:9", "duration_seconds": 10, "task_type": 22},
        user_id="7",
        world_id="9",
        auth_token="token",
    )
    executor.execute_tool(
        "image_to_video",
        {
            "prompt": "camera moves",
            "image_urls": "https://cdn.example.test/frame.png",
            "ratio": "16:9",
            "duration_seconds": 10,
            "image_mode": "multi_reference",
            "task_type": 22,  # Agent 自选 Seedance 2.0 Fast，必须被任务快照覆盖
        },
        user_id="7",
        world_id="9",
        auth_token="token",
    )

    assert [call["tool_name"] for call in delegated_calls] == [
        "generate_text_to_video",
        "image_to_video",
    ]
    for call in delegated_calls:
        assert call["tool_args"]["ratio"] == "9:16"
        assert call["tool_args"]["duration_seconds"] == 5
        assert call["tool_args"]["task_type"] == 27
        assert call["preferences"] == scoped_preferences
    assert delegated_calls[1]["tool_args"]["image_mode"] == "first_last_frame"
    assert mcp_tool._get_video_preferences("7", "9") == {"ratio": "16:9", "duration": 10}


def test_scene_scoped_digital_human_tool_submits_and_marks_asset_as_already_bound(monkeypatch):
    module = _load_video_tool_module()
    assert module is not None
    deduct = getattr(module, "deduct_storyboard_digital_human_computing_power", None)
    assert callable(deduct)

    delegated_calls = []

    class FakeDelegate:
        def get_tool_definitions(self, allowed_tools):
            return []

        def execute_tool(self, *args, **kwargs):
            delegated_calls.append((args, kwargs))
            return {"error": "should not delegate"}

    submitted = {}
    orchestrate_calls = {}

    fake_plan = SimpleNamespace(
        model="minimax_h3",
        task_type=35,
        speaker_character_id=1,
        speech_text="你好",
        speech_duration=2.5,
        first_frame_path="https://example.com/ff.png",
        ratio="16:9",
        billable_duration=4.0,
        prompt="图片1中的角色在说话。",
        audio_input="https://example.com/a.wav",
        audio_input_role="speech_audio",
        routing_reason="minimax_h3_only",
        resolution="720P",
        max_edge=1280,
        start_second=0,
        duration_clamp_reason="floor_to_4",
    )

    def fake_orchestrate(scene_id, **kwargs):
        orchestrate_calls.update(scene_id=scene_id, **kwargs)
        return fake_plan, [], None, None

    def fake_submit(plan, *, scene_id, user_id, transaction_id, computing_power,
                    clip_to_audio_duration=True, resolution=None):
        submitted.update(
            plan=plan, scene_id=scene_id, user_id=user_id,
            transaction_id=transaction_id, computing_power=computing_power,
            clip_to_audio_duration=clip_to_audio_duration, resolution=resolution,
        )
        return {
            "success": True,
            "ai_tool_id": 321,
            "asset_id": 654,
            "video_type": "digital_human",
            "task_type": 35,
            "model_used": "MiniMax H3",
        }

    from services import storyboard_digital_human_service

    monkeypatch.setattr(storyboard_digital_human_service, "orchestrate_digital_human_generation", fake_orchestrate)
    monkeypatch.setattr(storyboard_digital_human_service, "submit_digital_human_plan", fake_submit)
    monkeypatch.setattr(
        module,
        "deduct_storyboard_digital_human_computing_power",
        lambda **kwargs: ("transaction-1", 42),
    )

    executor = module.StoryboardAgentVideoToolExecutor(FakeDelegate(), scene_id=26)
    result = executor.execute_tool(
        "generate_digital_human",
        # Agent 传入的 prompt/duration/ratio 应被忽略（以服务端规划为准）
        {"prompt": "人物自然说话", "duration_seconds": 6, "aspect_ratio": "16:9",
         "resolution": "1080p", "clip_to_audio_duration": True},
        user_id="7",
        world_id="9",
        auth_token="token",
        model="model",
        vendor_id=3,
    )

    # submit 收到的是 plan（非 prompt/duration/ratio）
    assert submitted["plan"] is fake_plan
    assert submitted["scene_id"] == 26
    assert submitted["user_id"] == 7
    assert submitted["transaction_id"] == "transaction-1"
    assert submitted["computing_power"] == 42
    assert submitted["resolution"] == "1080p"
    assert submitted["clip_to_audio_duration"] is True
    assert result["project_ids"] == [321]
    assert result["already_bound"] is True
    assert executor.are_projects_already_bound([321]) is True
    assert delegated_calls == []


def test_frontend_skips_rebinding_scene_scoped_digital_human_task():
    events_js = (PROJECT_ROOT / "web" / "js" / "storyboard" / "events.js").read_text(
        encoding="utf-8"
    )
    handler_start = events_js.index("data.type === 'video_task_submitted'")
    handler_end = events_js.index("data.type === 'message'", handler_start)
    handler = events_js[handler_start:handler_end]

    assert "data.already_bound" in handler
    assert "loadSceneCandidates(streamSceneId)" in handler


def test_scene_scoped_digital_human_tool_does_not_charge_when_scene_is_not_ready(monkeypatch):
    module = _load_video_tool_module()
    assert module is not None

    class FakeDelegate:
        def get_tool_definitions(self, allowed_tools):
            return []

    from services import storyboard_digital_human_service
    from config.constant import StoryboardDigitalHumanConstants

    def fake_orchestrate(scene_id, **kwargs):
        raise storyboard_digital_human_service.StoryboardDigitalHumanError(
            StoryboardDigitalHumanConstants.ERROR_AUDIO_REQUIRED,
            "请先生成配音后再生成对口型视频",
        )

    monkeypatch.setattr(storyboard_digital_human_service, "orchestrate_digital_human_generation", fake_orchestrate)
    charged = []
    monkeypatch.setattr(
        module,
        "deduct_storyboard_digital_human_computing_power",
        lambda **kwargs: charged.append(kwargs),
    )

    executor = module.StoryboardAgentVideoToolExecutor(FakeDelegate(), scene_id=26)
    try:
        executor.execute_tool(
            "generate_digital_human",
            {"prompt": "自然说话", "duration_seconds": 5},
            user_id="7",
            world_id="9",
            auth_token="token",
        )
    except RuntimeError as exc:
        assert "配音" in str(exc)
    else:
        raise AssertionError("未就绪的对口型分镜必须拒绝提交")

    assert charged == []


def test_video_tool_executor_accepts_and_forwards_model_id():
    """回归：ExpertAgent 透传 model_id（受信模型路由），包装器签名必须接受并转发。"""
    module = _load_video_tool_module()
    assert module is not None

    delegated_calls = []

    class FakeDelegate:
        def get_tool_definitions(self, allowed_tools):
            return []

        def execute_tool(self, tool_name, tool_args, user_id, world_id, auth_token, **kwargs):
            delegated_calls.append({"tool_name": tool_name, "kwargs": kwargs})
            return {"success": True}

    executor = module.StoryboardAgentVideoToolExecutor(FakeDelegate(), scene_id=26)

    # 普通工具透传分支：get_user_computing_power 是线上报错路径
    executor.execute_tool(
        "get_user_computing_power",
        {},
        user_id="7",
        world_id="9",
        auth_token="token",
        model="deepseek-v4-flash",
        vendor_id=3,
        model_id=34,
    )
    assert delegated_calls[-1]["tool_name"] == "get_user_computing_power"
    assert delegated_calls[-1]["kwargs"].get("model_id") == 34

    # 标准视频工具分支同样透传
    executor.execute_tool(
        "generate_text_to_video",
        {"prompt": "camera moves"},
        user_id="7",
        world_id="9",
        auth_token="token",
        model_id=34,
    )
    assert delegated_calls[-1]["tool_name"] == "generate_text_to_video"
    assert delegated_calls[-1]["kwargs"].get("model_id") == 34
