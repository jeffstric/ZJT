from pathlib import Path
import json
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_scene_context_command_outputs_json(monkeypatch, capsys):
    from scripts import storyboard_agent_cli

    class FakeService:
        def scene_context(self, **kwargs):
            return {"success": True, "scene": {"id": kwargs["scene_id"]}}

    monkeypatch.setattr(storyboard_agent_cli, "StoryboardAgentCliService", lambda: FakeService())

    code = storyboard_agent_cli.main(["scene-context", "--scene-id", "12"])
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["scene"]["id"] == 12


def test_create_storyboard_from_script_command_outputs_storyboard_id(monkeypatch, capsys):
    from scripts import storyboard_agent_cli

    calls = []

    class FakeService:
        def create_storyboard_from_script(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "storyboard_id": 321, "script_id": kwargs["script_id"], "created": True}

    monkeypatch.setattr(storyboard_agent_cli, "StoryboardAgentCliService", lambda: FakeService())

    code = storyboard_agent_cli.main(
        [
            "create-storyboard-from-script",
            "--script-id",
            "123",
            "--user-id",
            "7",
        ]
    )
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["storyboard_id"] == 321
    assert calls[0]["script_id"] == 123
    assert calls[0]["user_id"] == 7


def test_generate_image_command_passes_mode_and_asset_type(monkeypatch, capsys):
    from scripts import storyboard_agent_cli

    calls = []

    class FakeService:
        def generate_image(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "project_ids": [1]}

    monkeypatch.setattr(storyboard_agent_cli, "StoryboardAgentCliService", lambda: FakeService())

    code = storyboard_agent_cli.main(
        [
            "generate-image",
            "--scene-id",
            "12",
            "--user-id",
            "7",
            "--mode",
            "image_edit",
            "--asset-type",
            "last_frame",
            "--source-image",
            "https://cdn.test/source.png",
            "--prompt",
            "edit",
        ]
    )
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["project_ids"] == [1]
    assert calls[0]["scene_id"] == 12
    assert calls[0]["user_id"] == 7
    assert calls[0]["mode"] == "image_edit"
    assert calls[0]["asset_type"] == "last_frame"


def test_generate_video_command_supports_image_to_video(monkeypatch, capsys):
    from scripts import storyboard_agent_cli

    calls = []

    class FakeService:
        def generate_video(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "project_ids": [2]}

    monkeypatch.setattr(storyboard_agent_cli, "StoryboardAgentCliService", lambda: FakeService())

    code = storyboard_agent_cli.main(
        [
            "generate-video",
            "--scene-id",
            "12",
            "--user-id",
            "7",
            "--mode",
            "image_to_video",
            "--image-mode",
            "first_last_with_ref",
        ]
    )
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["project_ids"] == [2]
    assert calls[0]["image_mode"] == "first_last_with_ref"


def test_auto_generate_missing_images_command(monkeypatch, capsys):
    from scripts import storyboard_agent_cli

    calls = []

    class FakeService:
        def auto_generate_missing_images(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "storyboard_id": kwargs["storyboard_id"], "submitted_count": 2}

    monkeypatch.setattr(storyboard_agent_cli, "StoryboardAgentCliService", lambda: FakeService())

    code = storyboard_agent_cli.main(
        [
            "auto-generate-missing-images",
            "--storyboard-id",
            "44",
            "--user-id",
            "7",
            "--auth-token",
            "short",
            "--limit",
            "3",
            "--image-size",
            "1K",
            "--sequence-mode",
            "quality",
        ]
    )
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["submitted_count"] == 2
    assert calls[0]["storyboard_id"] == 44
    assert calls[0]["user_id"] == 7
    assert calls[0]["limit"] == 3
    assert calls[0]["image_size"] == "1K"
    assert calls[0]["sequence_mode"] == "quality"


def test_storyboard_image_batch_status_command(monkeypatch, capsys):
    from scripts import storyboard_agent_cli

    calls = []

    class FakeService:
        def storyboard_image_batch_status(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "batch_id": kwargs["job_id"], "status": "running", "items": []}

    monkeypatch.setattr(storyboard_agent_cli, "StoryboardAgentCliService", lambda: FakeService())

    code = storyboard_agent_cli.main(
        [
            "storyboard-image-batch-status",
            "--batch-id",
            "88",
            "--user-id",
            "7",
        ]
    )
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["batch_id"] == 88
    assert calls[0]["job_id"] == 88
    assert calls[0]["user_id"] == 7


def test_storyboard_task_status_command(monkeypatch, capsys):
    from scripts import storyboard_agent_cli

    calls = []

    class FakeService:
        def storyboard_task_status(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "storyboard_id": kwargs["storyboard_id"], "scenes": []}

    monkeypatch.setattr(storyboard_agent_cli, "StoryboardAgentCliService", lambda: FakeService())

    code = storyboard_agent_cli.main(
        [
            "storyboard-task-status",
            "--storyboard-id",
            "44",
            "--user-id",
            "7",
            "--asset-type",
            "first_frame",
        ]
    )
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["storyboard_id"] == 44
    assert calls[0]["storyboard_id"] == 44
    assert calls[0]["user_id"] == 7
    assert calls[0]["asset_type"] == "first_frame"


def test_list_scenes_command(monkeypatch, capsys):
    from scripts import storyboard_agent_cli

    calls = []

    class FakeService:
        def list_scenes(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "storyboard_id": kwargs["storyboard_id"], "scenes": []}

    monkeypatch.setattr(storyboard_agent_cli, "StoryboardAgentCliService", lambda: FakeService())

    code = storyboard_agent_cli.main(
        [
            "list-scenes",
            "--storyboard-id",
            "44",
            "--user-id",
            "7",
        ]
    )
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["storyboard_id"] == 44
    assert calls[0]["storyboard_id"] == 44
    assert calls[0]["user_id"] == 7


def test_insert_scene_command(monkeypatch, capsys):
    from scripts import storyboard_agent_cli

    calls = []

    class FakeService:
        def insert_scene(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "storyboard_id": kwargs["storyboard_id"], "scene_id": 99}

    monkeypatch.setattr(storyboard_agent_cli, "StoryboardAgentCliService", lambda: FakeService())

    code = storyboard_agent_cli.main(
        [
            "insert-scene",
            "--storyboard-id",
            "44",
            "--user-id",
            "7",
            "--after-scene-id",
            "31",
            "--title",
            "Inserted",
            "--duration",
            "4",
            "--prompt-json",
            '{"scene_desc":"Inserted beat"}',
        ]
    )
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["scene_id"] == 99
    assert calls[0]["storyboard_id"] == 44
    assert calls[0]["user_id"] == 7
    assert calls[0]["after_scene_id"] == 31
    assert calls[0]["title"] == "Inserted"
    assert calls[0]["duration"] == 4
    assert calls[0]["prompt_json"] == '{"scene_desc":"Inserted beat"}'


def test_cli_errors_are_json(monkeypatch, capsys):
    from scripts import storyboard_agent_cli
    from services.storyboard_agent_cli_service import StoryboardCliError

    class FakeService:
        def scene_context(self, **kwargs):
            raise StoryboardCliError("not_found", "missing")

    monkeypatch.setattr(storyboard_agent_cli, "StoryboardAgentCliService", lambda: FakeService())

    code = storyboard_agent_cli.main(["scene-context", "--scene-id", "12"])
    out = json.loads(capsys.readouterr().out)

    assert code == 1
    assert out["success"] is False
    assert out["error_code"] == "not_found"
