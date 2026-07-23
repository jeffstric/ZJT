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
