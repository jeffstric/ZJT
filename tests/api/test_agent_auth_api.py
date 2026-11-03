from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client():
    from api.agent_auth import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_agent_auth_exchange_requires_token():
    response = _client().post("/api/agent-auth/exchange", json={})

    assert response.status_code == 401
    assert response.json()["success"] is False


def test_agent_auth_exchange_returns_auth_token(monkeypatch):
    client = _client()

    monkeypatch.setattr(
        "api.agent_auth.AgentAuthService.exchange_token",
        lambda raw_token, device_uuid=None: {
            "success": True,
            "auth_token": "short-lived-token",
            "user_id": 7,
            "expires_at": "2026-07-03T20:00:00",
            "token_type": "agent",
            "scopes": ["auth:exchange", "storyboard:generate"],
        },
    )

    response = client.post(
        "/api/agent-auth/exchange",
        json={"token": "agent-token", "device_uuid": "agent-device"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["auth_token"] == "short-lived-token"
    assert data["user_id"] == 7


# ===== 智能体 CLI 直接生图（POST /api/agent-auth/generate-image /image-status）=====

CONNECTION_TEXT = """请使用 $storyboard-agent-api 协助处理我的智剧通分镜。
连接信息如下，请不要把 token 放进 URL：
{
  "skill": "storyboard-agent-api",
  "base_url": "https://example.com",
  "agent_token": "agt_abc123",
  "environment": "prod"
}"""


def _patch_exchange(monkeypatch, user_id=7):
    monkeypatch.setattr(
        "api.agent_auth.AgentAuthService.exchange_token",
        lambda raw_token, device_uuid=None: {
            "success": True, "auth_token": "auth-token-1",
            "user_id": user_id, "token_type": "agent",
        },
    )


def test_generate_image_requires_connection_info():
    response = _client().post(
        "/api/agent-auth/generate-image",
        json={"prompt": "一只橘猫"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "missing_agent_token"


def test_generate_image_rejects_invalid_prompt(monkeypatch):
    _patch_exchange(monkeypatch)
    response = _client().post(
        "/api/agent-auth/generate-image",
        json={"connection_info": CONNECTION_TEXT, "prompt": "   "},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "prompt_required"


def test_generate_image_submits_text_to_image(monkeypatch):
    _patch_exchange(monkeypatch)
    # connection_info 提取 agent_token → exchange；模型走显式 moss
    monkeypatch.setattr(
        "services.agent_image_service.WorldModel.list_by_user",
        lambda **kwargs: {"data": [SimpleNamespace(id=1, user_id=7)]},
    )
    monkeypatch.setattr(
        "services.agent_image_service.MediaGenerationPreferenceService.get_profile",
        lambda *args, **kwargs: None,
    )
    submitted = {}

    def _fake_t2i(**kwargs):
        submitted.update(kwargs)
        return {"success": True, "project_ids": [501], "computing_power_required": 1,
                "computing_power_total": 1, "image_size_used": "2K"}

    import types as _types
    monkeypatch.setitem(
        __import__("sys").modules, "script_writer_core.mcp_tool",
        _types.SimpleNamespace(generate_text_to_image=_fake_t2i, edit_image=lambda **k: {}),
    )

    response = _client().post(
        "/api/agent-auth/generate-image",
        json={"connection_info": CONNECTION_TEXT, "prompt": "一只戴墨镜的橘猫",
              "model": "moss", "ratio": "9:16"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["project_ids"] == [501]
    assert data["task_type"] == 53
    assert data["model_key"] == "moss"
    assert data["mode"] == "text_to_image"
    assert data["poll_hint"]["endpoint"] == "POST /api/agent-auth/image-status"
    # agent_token 从粘贴文本提取并换成了 auth_token 传递
    assert submitted["auth_token"] == "auth-token-1"
    assert submitted["task_type"] == 53
    assert submitted["aspect_ratio"] == "9:16"


def test_generate_image_moss_with_reference_rejected(monkeypatch):
    _patch_exchange(monkeypatch)
    monkeypatch.setattr(
        "services.agent_image_service.WorldModel.list_by_user",
        lambda **kwargs: {"data": [SimpleNamespace(id=1, user_id=7)]},
    )
    response = _client().post(
        "/api/agent-auth/generate-image",
        json={"connection_info": CONNECTION_TEXT, "prompt": "p",
              "model": "moss", "reference_image": "https://a.png"},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error_code"] == "model_mode_unsupported"
    assert "仅支持文生图" in data["error"]


def _patch_identify(monkeypatch, user_id=7):
    monkeypatch.setattr(
        "services.agent_image_service.AgentAuthService.resolve_agent_user",
        lambda raw_token: {"success": True, "user_id": user_id, "token_type": "agent"},
    )


def test_image_status_returns_terminal(monkeypatch):
    _patch_identify(monkeypatch)
    monkeypatch.setattr(
        "services.agent_image_service.AIToolModel.get_by_id",
        lambda project_id: SimpleNamespace(
            id=501, user_id=7, status=2, result_url="http://x/a.png", message="done"),
    )
    response = _client().post(
        "/api/agent-auth/image-status",
        json={"connection_info": CONNECTION_TEXT, "project_id": 501},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["terminal"] is True
    assert data["status"] == "COMPLETED"
    assert data["result_url"] == "http://x/a.png"


def test_image_status_does_not_mint_session(monkeypatch):
    minted = []
    monkeypatch.setattr(
        "services.agent_auth_service.UserTokensModel.create",
        lambda *args, **kwargs: minted.append(args) or 1,
    )
    _patch_identify(monkeypatch)
    monkeypatch.setattr(
        "services.agent_image_service.AIToolModel.get_by_id",
        lambda project_id: SimpleNamespace(
            id=501, user_id=7, status=1, result_url=None, message=None),
    )
    response = _client().post(
        "/api/agent-auth/image-status",
        json={"agent_token": "agt_abc123", "project_id": 501},
    )
    assert response.status_code == 200
    assert minted == []


def test_image_status_owner_isolation(monkeypatch):
    _patch_identify(monkeypatch, user_id=7)
    monkeypatch.setattr(
        "services.agent_image_service.AIToolModel.get_by_id",
        lambda project_id: SimpleNamespace(id=501, user_id=99, status=2, result_url="http://x", message=None),
    )
    response = _client().post(
        "/api/agent-auth/image-status",
        json={"connection_info": CONNECTION_TEXT, "project_id": 501},
    )
    assert response.status_code == 404
