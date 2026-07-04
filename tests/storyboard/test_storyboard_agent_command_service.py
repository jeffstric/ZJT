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
