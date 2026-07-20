from types import SimpleNamespace
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_storyboard_agent_command_schema_lists_commands():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    schema = StoryboardAgentCommandService().schema()
    command_names = [item["name"] for item in schema["commands"]]

    assert "generate-image" in command_names
    assert schema["environment"]
    assert "scene-context" in command_names
    assert "list-scenes" in command_names
    assert "insert-scene" in command_names
    assert "auto-generate-missing-images" in command_names
    assert "storyboard-task-status" in command_names
    create_command = next(
        item for item in schema["commands"]
        if item["name"] == "create-storyboard-from-script"
    )
    assert {"model", "model_id", "vendor_id"}.issubset(create_command["params"])
    world_context = next(
        item for item in schema["commands"] if item["name"] == "world-context"
    )
    assert world_context["response"]["scripts"] == "Page<object>"
    assert world_context["response"]["characters"] == "Page<object>"
    status_command = next(
        item for item in schema["commands"] if item["name"] == "storyboard-task-status"
    )
    assert (
        status_command["response"]["result_url_path"]
        == "scenes[].selected_assets.first_frame.result_url"
    )


def test_create_storyboard_command_dispatches_model_selection():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def create_storyboard_from_script(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "storyboard_id": 9}

    result = StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "create-storyboard-from-script",
        {
            "script_id": 20,
            "user_id": 7,
            "model": "deepseek-v4-pro",
            "model_id": 1008,
            "vendor_id": 10,
        },
    )

    assert result["success"] is True
    assert calls[0]["model"] == "deepseek-v4-pro"
    assert calls[0]["model_id"] == 1008
    assert calls[0]["vendor_id"] == 10


def test_create_storyboard_cli_accepts_model_selection():
    from scripts.storyboard_agent_cli import build_parser

    args = build_parser().parse_args([
        "create-storyboard-from-script",
        "--script-id", "20",
        "--user-id", "7",
        "--model", "deepseek-v4-pro",
        "--model-id", "1008",
        "--vendor-id", "10",
    ])

    assert args.model == "deepseek-v4-pro"
    assert args.model_id == 1008
    assert args.vendor_id == 10


def test_storyboard_agent_command_execute_dispatches_to_storyboard_service():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def generate_image(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "scene_id": kwargs["scene_id"], "project_ids": [101]}

    result = StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "generate-image",
        {"scene_id": 12, "user_id": 7, "mode": "auto", "asset_type": "first_frame"},
    )

    assert result["success"] is True
    assert result["environment"]
    assert result["project_ids"] == [101]
    assert calls[0]["scene_id"] == 12
    assert calls[0]["user_id"] == 7
    assert calls[0]["mode"] == "auto"


def test_storyboard_agent_command_rejects_unknown_command():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService
    from services.storyboard_agent_cli_service import StoryboardCliError

    try:
        StoryboardAgentCommandService(service=SimpleNamespace()).execute("missing-command", {})
    except StoryboardCliError as exc:
        assert exc.error_code == "unknown_command"
    else:
        raise AssertionError("expected StoryboardCliError")


def test_storyboard_agent_command_dispatches_auto_generate_missing_images():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def auto_generate_missing_images(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "storyboard_id": kwargs["storyboard_id"], "submitted_count": 1}

    result = StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "auto-generate-missing-images",
        {
            "storyboard_id": 44,
            "user_id": 7,
            "auth_token": "token",
            "limit": 3,
            "asset_type": "first_frame",
            "sequence_mode": "balanced",
        },
    )

    assert result["success"] is True
    assert result["submitted_count"] == 1
    assert calls[0]["storyboard_id"] == 44
    assert calls[0]["user_id"] == 7
    assert calls[0]["auth_token"] == "token"
    assert calls[0]["limit"] == 3
    assert calls[0]["sequence_mode"] == "balanced"


def test_storyboard_agent_command_dispatches_image_batch_status():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def storyboard_image_batch_status(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "batch_id": kwargs["job_id"], "status": "running"}

    result = StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "storyboard-image-batch-status",
        {"batch_id": 88, "user_id": 7},
    )

    assert result["success"] is True
    assert result["batch_id"] == 88
    assert calls[0]["job_id"] == 88
    assert calls[0]["user_id"] == 7


def test_storyboard_agent_command_dispatches_storyboard_task_status():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def storyboard_task_status(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "storyboard_id": kwargs["storyboard_id"], "scenes": []}

    result = StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "storyboard-task-status",
        {"storyboard_id": 44, "user_id": 7, "asset_type": "first_frame"},
    )

    assert result["success"] is True
    assert result["storyboard_id"] == 44
    assert calls[0]["storyboard_id"] == 44
    assert calls[0]["user_id"] == 7
    assert calls[0]["asset_type"] == "first_frame"


def test_storyboard_agent_command_dispatches_list_scenes():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def list_scenes(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "storyboard_id": kwargs["storyboard_id"], "scenes": []}

    result = StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "list-scenes",
        {"storyboard_id": 44, "user_id": 7},
    )

    assert result["success"] is True
    assert result["storyboard_id"] == 44
    assert calls[0]["storyboard_id"] == 44
    assert calls[0]["user_id"] == 7


def test_storyboard_agent_command_dispatches_insert_scene():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def insert_scene(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "scene_id": 99, "storyboard_id": kwargs["storyboard_id"]}

    result = StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "insert-scene",
        {
            "storyboard_id": 44,
            "user_id": 7,
            "after_scene_id": 31,
            "title": "Inserted",
            "duration": 4,
            "prompt_json": {"scene_desc": "Inserted beat"},
        },
    )

    assert result["success"] is True
    assert result["scene_id"] == 99
    assert calls[0]["storyboard_id"] == 44
    assert calls[0]["user_id"] == 7
    assert calls[0]["after_scene_id"] == 31
    assert calls[0]["title"] == "Inserted"
    assert calls[0]["duration"] == 4


def test_storyboard_agent_command_dispatches_split_force_overwrite_subscene_grids():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def split_from_script(self, **kwargs):
            calls.append(kwargs)
            return {
                "success": True,
                "storyboard_id": kwargs["storyboard_id"],
                "status": "queued",
                "task_id": "task-fake-1",
                "status_url": "/api/script-split/tasks/task-fake-1",
            }

    result = StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "split-from-script",
        {
            "storyboard_id": 44,
            "user_id": 7,
            "auth_token": "token",
            "model": "deepseek-v4-pro",
            "force_overwrite_subscene_grids": True,
        },
    )

    assert result["success"] is True
    assert calls[0]["force_overwrite_subscene_grids"] is False
    assert calls[0]["model"] == "deepseek-v4-pro"


def test_split_from_script_requires_model():
    """split-from-script 缺 model 时拒绝（CLI 路径强制，不再回退默认 gemini）。

    _to_required_str 抛 StoryboardCliError，与 _to_required_int 同模式；
    HTTP 路由层（api/storyboard.py）会捕获它转成 JSON 错误响应。
    """
    import pytest
    from services.storyboard_agent_command_service import StoryboardAgentCommandService
    from services.storyboard_agent_cli_service import StoryboardCliError

    class FakeStoryboardService:
        def split_from_script(self, **kwargs):
            raise AssertionError("缺 model 时不应进入 service")

    with pytest.raises(StoryboardCliError) as exc_info:
        StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
            "split-from-script",
            {"storyboard_id": 44, "user_id": 7, "auth_token": "token"},
        )

    assert exc_info.value.error_code == "missing_parameter"
    assert "model" in exc_info.value.message


def test_split_from_script_requires_auth_token():
    """split-from-script 缺 auth_token 时拒绝。

    worker 调 LLM 的 token 算力由 auth_token 解析出的 user_id 承担；漏传会导致
    LLM 免费消耗（token_log 门禁 if auth_token 被跳过）。与数字人路径对齐。
    """
    import pytest
    from services.storyboard_agent_command_service import StoryboardAgentCommandService
    from services.storyboard_agent_cli_service import StoryboardCliError

    class FakeStoryboardService:
        def split_from_script(self, **kwargs):
            raise AssertionError("缺 auth_token 时不应进入 service")

    with pytest.raises(StoryboardCliError) as exc_info:
        StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
            "split-from-script",
            {"storyboard_id": 44, "user_id": 7, "model": "m"},  # 无 auth_token
        )

    assert exc_info.value.error_code == "missing_auth_token"
    assert "auth_token" in exc_info.value.message


def test_split_from_script_max_group_duration_range():
    """max_group_duration 强制 10~15 范围：低于 10 或高于 15 都拒绝。
    低于 10 会让分段碎、画面增多，导致同世界画风一致性下降。"""
    import pytest
    from services.storyboard_agent_command_service import StoryboardAgentCommandService
    from services.storyboard_agent_cli_service import StoryboardCliError

    class FakeStoryboardService:
        def split_from_script(self, **kwargs):
            raise AssertionError("超范围时不应进入 service")

    # 合法值应放行（这里 FakeService 会抛 AssertionError 表示已进入，用另一个 stub）
    class OkService:
        def split_from_script(self, **kwargs):
            return {"success": True, "max_group_duration": kwargs["max_group_duration"]}

    for ok in [10, 12, 15]:
        result = StoryboardAgentCommandService(service=OkService()).execute(
            "split-from-script",
            {"storyboard_id": 44, "user_id": 7, "auth_token": "token", "model": "m", "max_group_duration": ok},
        )
        assert result["max_group_duration"] == ok, f"{ok} 应放行"

    # 非法值应拒绝
    for bad in [6, 8, 16, 20]:
        with pytest.raises(StoryboardCliError) as exc_info:
            StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
                "split-from-script",
                {"storyboard_id": 44, "user_id": 7, "auth_token": "token", "model": "m", "max_group_duration": bad},
            )
        assert exc_info.value.error_code == "invalid_parameter"
        assert "max_group_duration" in exc_info.value.message
        assert "10" in exc_info.value.message and "15" in exc_info.value.message


def test_schema_lists_export_commands():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    schema = StoryboardAgentCommandService().schema()
    command_names = [item["name"] for item in schema["commands"]]

    assert "export-check" in command_names
    assert "export-full-video" in command_names
    assert "export-package" in command_names

    export_check = next(
        item for item in schema["commands"] if item["name"] == "export-check"
    )
    assert export_check["permission"] == "storyboard:export"
    assert "storyboard_id" in export_check["params"]
    assert export_check["response"]["total_scenes"] == "int"

    export_full_video = next(
        item for item in schema["commands"] if item["name"] == "export-full-video"
    )
    assert "include_subtitles" in export_full_video["params"]
    assert export_full_video["response"]["download_url"] == "string"

    export_package = next(
        item for item in schema["commands"] if item["name"] == "export-package"
    )
    assert export_package["response"]["download_url"] == "string"


def test_export_check_dispatches_to_service():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def export_check(self, **kwargs):
            calls.append(kwargs)
            return {
                "success": True,
                "storyboard_id": kwargs["storyboard_id"],
                "total_scenes": 5,
                "ready_scenes": 4,
                "missing_scenes": 1,
                "details": [],
            }

    result = StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "export-check",
        {"storyboard_id": 42, "user_id": 7},
    )

    assert result["success"] is True
    assert result["total_scenes"] == 5
    assert calls[0]["storyboard_id"] == 42
    assert calls[0]["user_id"] == 7


def test_export_full_video_dispatches_with_default_subtitles():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def export_full_video(self, **kwargs):
            calls.append(kwargs)
            return {
                "success": True,
                "download_url": "https://cdn.example.com/video.mp4",
                "filename": "video.mp4",
            }

    result = StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "export-full-video",
        {"storyboard_id": 42, "user_id": 7},
    )

    assert result["success"] is True
    assert result["download_url"] == "https://cdn.example.com/video.mp4"
    assert calls[0]["storyboard_id"] == 42
    assert calls[0]["user_id"] == 7
    assert calls[0]["include_subtitles"] is True


def test_export_full_video_dispatches_with_subtitles_false():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def export_full_video(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "download_url": "x", "filename": "x"}

    StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "export-full-video",
        {"storyboard_id": 42, "user_id": 7, "include_subtitles": False},
    )

    assert calls[0]["include_subtitles"] is False


def test_export_package_dispatches_to_service():
    from services.storyboard_agent_command_service import StoryboardAgentCommandService

    calls = []

    class FakeStoryboardService:
        def export_package(self, **kwargs):
            calls.append(kwargs)
            return {
                "success": True,
                "download_url": "https://cdn.example.com/assets.zip",
                "filename": "assets.zip",
            }

    result = StoryboardAgentCommandService(service=FakeStoryboardService()).execute(
        "export-package",
        {"storyboard_id": 42, "user_id": 7},
    )

    assert result["success"] is True
    assert result["download_url"] == "https://cdn.example.com/assets.zip"
    assert calls[0]["storyboard_id"] == 42
    assert calls[0]["user_id"] == 7


def test_export_cli_parser_accepts_export_check():
    from scripts.storyboard_agent_cli import build_parser

    args = build_parser().parse_args([
        "export-check",
        "--storyboard-id", "42",
        "--user-id", "7",
    ])

    assert args.command == "export-check"
    assert args.storyboard_id == 42
    assert args.user_id == 7


def test_export_cli_parser_accepts_export_full_video():
    from scripts.storyboard_agent_cli import build_parser

    args = build_parser().parse_args([
        "export-full-video",
        "--storyboard-id", "42",
        "--user-id", "7",
    ])

    assert args.command == "export-full-video"
    assert args.storyboard_id == 42
    assert args.user_id == 7
    assert args.include_subtitles is True


def test_export_cli_parser_accepts_export_full_video_no_subtitles():
    from scripts.storyboard_agent_cli import build_parser

    args = build_parser().parse_args([
        "export-full-video",
        "--storyboard-id", "42",
        "--user-id", "7",
        "--no-subtitles",
    ])

    assert args.include_subtitles is False


def test_export_cli_parser_accepts_export_package():
    from scripts.storyboard_agent_cli import build_parser

    args = build_parser().parse_args([
        "export-package",
        "--storyboard-id", "42",
        "--user-id", "7",
    ])

    assert args.command == "export-package"
    assert args.storyboard_id == 42
    assert args.user_id == 7
