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
