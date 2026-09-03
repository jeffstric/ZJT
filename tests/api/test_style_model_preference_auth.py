from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.script_writer as script_writer


def _client():
    app = FastAPI()
    app.include_router(script_writer.router)
    return TestClient(app)


def test_style_model_preference_requires_authorization():
    response = _client().post(
        "/api/style-models/preference",
        json={"user_id": "7", "world_id": "3", "model": "vl-model"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "missing_auth_token"


def test_style_model_preference_rejects_spoofed_body_user(monkeypatch):
    async def fake_resolve(_token):
        return 7, None

    monkeypatch.setattr(script_writer, "resolve_authorization_user_id", fake_resolve)
    response = _client().post(
        "/api/style-models/preference",
        headers={"Authorization": "token", "X-User-Id": "7"},
        json={"user_id": "8", "world_id": "3", "model": "vl-model"},
    )

    assert response.status_code == 403
    assert response.json()["success"] is False


def test_style_model_preference_uses_token_user_for_permission_and_write(monkeypatch):
    calls = {}

    async def fake_resolve(_token):
        return 7, None

    def fake_ensure(world_id, user_id, action):
        calls["permission"] = (world_id, user_id, action)

    def fake_set(user_id, world_id, model, model_id=None, vendor_id=None):
        calls["write"] = (user_id, world_id, model, model_id, vendor_id)
        return True

    monkeypatch.setattr(script_writer, "resolve_authorization_user_id", fake_resolve)
    monkeypatch.setattr(script_writer, "ensure_world_access", fake_ensure)
    monkeypatch.setattr(script_writer, "set_vl_model_preference", fake_set)

    response = _client().post(
        "/api/style-models/preference",
        headers={"Authorization": "token", "X-User-Id": "7"},
        json={
            "user_id": "7",
            "world_id": "3",
            "model": "vl-model",
            "model_id": 11,
            "vendor_id": 5,
        },
    )

    assert response.status_code == 200
    assert calls["permission"] == (3, 7, script_writer.Action.EDIT)
    assert calls["write"] == ("7", "3", "vl-model", 11, 5)
