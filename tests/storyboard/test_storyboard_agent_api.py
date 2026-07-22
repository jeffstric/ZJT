from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _client():
    from api.storyboard import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_storyboard_agent_schema_requires_auth():
    response = _client().get("/api/storyboard/agent/schema")

    assert response.status_code == 401
    assert response.json()["success"] is False


def test_storyboard_agent_command_uses_authenticated_user(monkeypatch):
    client = _client()
    calls = []

    monkeypatch.setattr("api.storyboard.UserTokensModel.get_user_id_by_token", lambda token: 7)
    monkeypatch.setattr(
        "api.storyboard.StoryboardAgentCommandService.schema",
        lambda self: {"success": True, "commands": []},
        raising=False,
    )
    monkeypatch.setattr(
        "api.storyboard.StoryboardAgentCommandService.execute",
        lambda self, command, params: calls.append((command, params)) or {
            "success": True,
            "scene_id": params["scene_id"],
            "user_id": params["user_id"],
        },
        raising=False,
    )

    schema_response = client.get(
        "/api/storyboard/agent/schema",
        headers={"Authorization": "Bearer short-lived-token"},
    )
    assert schema_response.status_code == 200

    response = client.post(
        "/api/storyboard/agent/commands/scene-context",
        headers={"Authorization": "Bearer short-lived-token"},
        json={"scene_id": 12, "user_id": 999},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == 7
    assert calls[0][0] == "scene-context"
    assert calls[0][1]["user_id"] == 7


def test_storyboard_agent_command_rejects_invalid_json_body(monkeypatch):
    client = _client()

    monkeypatch.setattr("api.storyboard.UserTokensModel.get_user_id_by_token", lambda token: 7)

    response = client.post(
        "/api/storyboard/agent/commands/create-storyboard-from-script",
        headers={
            "Authorization": "Bearer short-lived-token",
            "Content-Type": "application/json",
        },
        content="{bad-json",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_body"


def test_storyboard_auto_generate_missing_images_uses_authenticated_user(monkeypatch):
    client = _client()
    calls = []

    monkeypatch.setattr("api.storyboard.UserTokensModel.get_user_id_by_token", lambda token: 7)
    monkeypatch.setattr(
        "api.storyboard.StoryboardAgentCommandService.execute",
        lambda self, command, params: calls.append((command, params)) or {
            "success": True,
            "storyboard_id": params["storyboard_id"],
            "user_id": params["user_id"],
            "submitted_count": 1,
        },
        raising=False,
    )

    response = client.post(
        "/api/storyboard/44/auto-generate-missing-images",
        headers={"Authorization": "Bearer short-lived-token"},
        json={
            "user_id": 999,
            "limit": 2,
            "scene_ids": [11, 12],
            "existing_policy": "regenerate",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["submitted_count"] == 1
    assert data["user_id"] == 7
    assert calls[0][0] == "auto-generate-missing-images"
    assert calls[0][1]["storyboard_id"] == 44
    assert calls[0][1]["user_id"] == 7
    assert calls[0][1]["auth_token"] == "short-lived-token"
    assert calls[0][1]["scene_ids"] == [11, 12]
    assert calls[0][1]["existing_policy"] == "regenerate"


def test_storyboard_auto_generate_missing_images_returns_403_for_enterprise_only(monkeypatch):
    from services.storyboard_agent_cli_service import StoryboardCliError

    client = _client()

    monkeypatch.setattr("api.storyboard.UserTokensModel.get_user_id_by_token", lambda token: 7)

    def fake_execute(self, command, params):
        raise StoryboardCliError("enterprise_only", "效果模式仅商业版支持，请购买商业版后使用")

    monkeypatch.setattr(
        "api.storyboard.StoryboardAgentCommandService.execute",
        fake_execute,
        raising=False,
    )

    response = client.post(
        "/api/storyboard/44/auto-generate-missing-images",
        headers={"Authorization": "Bearer short-lived-token"},
        json={"sequence_mode": "quality"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "enterprise_only"


def test_storyboard_auto_generate_missing_images_returns_409_for_active_batch(monkeypatch):
    from services.storyboard_agent_cli_service import StoryboardCliError

    client = _client()

    monkeypatch.setattr("api.storyboard.UserTokensModel.get_user_id_by_token", lambda token: 7)

    def fake_execute(self, command, params):
        raise StoryboardCliError(
            "active_batch_exists",
            "当前故事板已有自动生成任务正在进行，请等待完成后再发起新的生成。",
            payload={"active_batch_id": 88},
        )

    monkeypatch.setattr(
        "api.storyboard.StoryboardAgentCommandService.execute",
        fake_execute,
        raising=False,
    )

    response = client.post(
        "/api/storyboard/44/auto-generate-missing-images",
        headers={"Authorization": "Bearer short-lived-token"},
        json={"sequence_mode": "speed"},
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "active_batch_exists"
    assert response.json()["active_batch_id"] == 88


def test_storyboard_auto_generate_missing_images_returns_202_while_location_grids_run(monkeypatch):
    from services.storyboard_agent_cli_service import StoryboardCliError

    client = _client()
    monkeypatch.setattr("api.storyboard.UserTokensModel.get_user_id_by_token", lambda token: 7)

    def fake_execute(self, command, params):
        raise StoryboardCliError(
            "waiting_location_references",
            "场景参考图生成中",
            payload={"retry_after_ms": 3000, "running_tasks": [{"grid_task_id": 9}]},
        )

    monkeypatch.setattr(
        "api.storyboard.StoryboardAgentCommandService.execute",
        fake_execute,
        raising=False,
    )

    response = client.post(
        "/api/storyboard/44/auto-generate-missing-images",
        headers={"Authorization": "Bearer short-lived-token"},
        json={"sequence_mode": "quality"},
    )

    assert response.status_code == 202
    assert response.json()["error_code"] == "waiting_location_references"
    assert response.json()["retry_after_ms"] == 3000


def test_storyboard_batch_task_status_uses_authenticated_user(monkeypatch):
    client = _client()
    calls = []

    monkeypatch.setattr("api.storyboard.UserTokensModel.get_user_id_by_token", lambda token: 7)
    monkeypatch.setattr(
        "api.storyboard.StoryboardAgentCommandService.execute",
        lambda self, command, params: calls.append((command, params)) or {
            "success": True,
            "storyboard_id": params["storyboard_id"],
            "user_id": params["user_id"],
            "scenes": [],
        },
        raising=False,
    )

    response = client.get(
        "/api/storyboard/44/task-status?asset_type=first_frame",
        headers={"Authorization": "Bearer short-lived-token"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["storyboard_id"] == 44
    assert data["user_id"] == 7
    assert calls[0][0] == "storyboard-task-status"
    assert calls[0][1]["asset_type"] == "first_frame"
