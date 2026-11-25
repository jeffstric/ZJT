"""绑定管理 admin API 的薄层测试：鉴权与错误码透传。"""

from types import SimpleNamespace

import pytest

from api import user_module_admin as admin_api
from services.user_module_binding_service import UserModuleBindingError


@pytest.fixture()
def admin_auth(monkeypatch):
    async def _fake_require(authorization):
        return SimpleNamespace(role="admin"), None

    monkeypatch.setattr(admin_api, "_require_admin_user", _fake_require)


def _patch_to_thread(monkeypatch, fn):
    """把 asyncio.to_thread 替换为在协程内同步执行 fn 的版本。"""

    async def _awaitable_call(target, *args, **kwargs):
        return target(*args, **kwargs)

    monkeypatch.setattr(
        admin_api.asyncio,
        "to_thread",
        lambda target, *args, **kwargs: _awaitable_call(target, *args, **kwargs),
    )
    return fn


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(admin_api.router)
    return TestClient(app)


def test_list_binding_targets_returns_payload(admin_auth, monkeypatch):
    payload = {"capabilities": [{"operation": "text_to_video", "media_kind": "video"}], "tasks": {}}
    _patch_to_thread(monkeypatch, None)
    import services.user_module_binding_service as svc

    monkeypatch.setattr(svc, "list_binding_targets", lambda _mid: payload)
    response = _client().get("/api/admin/user-modules/binding-targets?module_id=huimeng.grok_video")
    assert response.status_code == 200
    assert response.json()["data"] == payload


def test_create_binding_maps_binding_error_to_400(admin_auth, monkeypatch):
    def _raise(*_a, **_k):
        raise UserModuleBindingError("CATEGORY_MISMATCH", "分类不匹配")

    _patch_to_thread(monkeypatch, None)
    import services.user_module_binding_service as svc

    monkeypatch.setattr(svc, "create_binding", _raise)

    response = _client().post(
        "/api/admin/user-modules/huimeng.grok_video/bindings",
        json={"module_id": "huimeng.grok_video", "task_id": 1, "operation": "text_to_video"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "CATEGORY_MISMATCH"


def test_create_binding_rejects_module_id_mismatch(admin_auth):
    response = _client().post(
        "/api/admin/user-modules/other.module/bindings",
        json={"module_id": "huimeng.grok_video", "task_id": 1, "operation": "text_to_video"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "module_id_mismatch"
