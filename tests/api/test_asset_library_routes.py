"""资产库用户侧路由（/api/asset-library/*）回归测试。

service 层已有 tests/services/test_asset_library_service.py 充分覆盖；
本文件守护路由层接线语义：
- _feature_guard：Depends 内的业务异常必须转成对应 HTTP 码（feature_disabled→403），
  未登录→401（guard 在 require_permission 注入 state 之前自行解析身份）
- _http_error 映射：not_found/group_not_found 统一 404（防枚举）、
  quota_exceeded→403、其余→400
- list_assets 的 group_scope=ungrouped → effective_group="ungrouped" 字符串
- /status 三元判定（enabled + admin/allow_all_users/白名单）
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import perseids_server.utils.permission as permission_utils
from api import asset_library as al_api
from services.asset_library_service import AssetLibraryError


def _client(monkeypatch, *, role="user", allowed=True):
    app = FastAPI()
    app.include_router(al_api.router)
    client = TestClient(app)

    from model.user_tokens import UserTokensModel
    monkeypatch.setattr(
        UserTokensModel, "get_user_id_by_token",
        staticmethod(lambda t: 7 if t == "tok-7" else None),
    )

    async def fake_resolve(auth_value):
        return 7, None

    monkeypatch.setattr(
        permission_utils, "resolve_authorization_user_id", fake_resolve
    )

    users = MagicMock()
    users.get_by_id.return_value = SimpleNamespace(id=7, role=role)
    monkeypatch.setattr(al_api, "UsersModel", users)

    def fake_ensure(user_id, is_admin):
        if not allowed:
            raise AssetLibraryError("资产库功能未开放", "feature_disabled")

    monkeypatch.setattr(al_api.svc, "ensure_user_allowed", fake_ensure)
    return client


AUTH = {"Authorization": "Bearer tok-7"}


def test_feature_guard_disabled_returns_403(monkeypatch):
    client = _client(monkeypatch, allowed=False)
    resp = client.get("/api/asset-library/assets", headers=AUTH)
    assert resp.status_code == 403
    assert "未开放" in resp.json()["detail"]


def test_feature_guard_unauthenticated_returns_401(monkeypatch):
    client = _client(monkeypatch)

    async def reject(auth_value):
        return None, SimpleNamespace(status_code=401)

    # _feature_guard 函数内 from auth_identity import（与 permission 模块各持一份绑定）
    import perseids_server.utils.auth_identity as auth_identity
    monkeypatch.setattr(auth_identity, "resolve_authorization_user_id", reject)
    monkeypatch.setattr(permission_utils, "resolve_authorization_user_id", reject)
    resp = client.get("/api/asset-library/assets", headers=AUTH)
    assert resp.status_code == 401


def test_not_found_mapped_to_404(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        al_api.svc, "get_asset_detail",
        MagicMock(side_effect=AssetLibraryError("资产不存在", "not_found")),
    )
    resp = client.get("/api/asset-library/assets/99", headers=AUTH)
    assert resp.status_code == 404


def test_group_not_found_also_mapped_to_404(monkeypatch):
    """group_not_found 与 not_found 同为 404：不泄漏"分组存在与否"。"""
    client = _client(monkeypatch)
    monkeypatch.setattr(
        al_api.svc, "rename_group",
        MagicMock(side_effect=AssetLibraryError("分组不存在", "group_not_found")),
    )
    resp = client.put(
        "/api/asset-library/groups/5", headers=AUTH, json={"name": "新名"})
    assert resp.status_code == 404


def test_quota_exceeded_mapped_to_403(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        al_api.svc, "add_asset",
        MagicMock(side_effect=AssetLibraryError("容量不足", "quota_exceeded")),
    )
    resp = client.post(
        "/api/asset-library/assets", headers=AUTH,
        json={"source_url": "https://cdn.example.com/a.png"})
    assert resp.status_code == 403


def test_invalid_url_mapped_to_400(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        al_api.svc, "add_asset",
        MagicMock(side_effect=AssetLibraryError("地址不合法", "invalid_source")),
    )
    resp = client.post(
        "/api/asset-library/assets", headers=AUTH,
        json={"source_url": "javascript:alert(1)"})
    assert resp.status_code == 400


def test_list_assets_ungrouped_scope_passes_string(monkeypatch):
    """group_scope=ungrouped 时 service 收到字符串 "ungrouped"，而非 group_id。"""
    client = _client(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        al_api.svc, "list_assets",
        MagicMock(return_value={"items": [], "has_more": False}),
    )

    resp = client.get(
        "/api/asset-library/assets",
        params={"group_scope": "ungrouped"},
        headers=AUTH,
    )
    assert resp.status_code == 200
    args = al_api.svc.list_assets.call_args[0]
    # (user_id, page, page_size, effective_group, asset_type, keyword, scope, is_admin, lite)
    assert args[3] == "ungrouped"
    assert args[7] is False  # 普通用户


def test_list_assets_plain_group_id_passthrough(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        al_api.svc, "list_assets",
        MagicMock(return_value={"items": [], "has_more": False}),
    )
    resp = client.get(
        "/api/asset-library/assets", params={"group_id": 12}, headers=AUTH)
    assert resp.status_code == 200
    assert al_api.svc.list_assets.call_args[0][3] == 12


def test_list_groups_injects_can_manage(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        al_api.svc, "list_groups",
        MagicMock(return_value=(
            [{"id": 1, "name": "g1", "creator_user_id": 7},
             {"id": 2, "name": "g2", "creator_user_id": 8}],
            3,
        )),
    )
    resp = client.get("/api/asset-library/groups", headers=AUTH)
    data = resp.json()["data"]
    assert data["ungrouped_count"] == 3
    assert data["groups"][0]["can_manage"] is True   # 属主
    assert data["groups"][1]["can_manage"] is False  # 他人分组


def test_status_allowed_for_whitelisted_user(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        al_api.svc, "get_feature_config",
        MagicMock(return_value={
            "enabled": True, "allow_all_users": False,
            "total_quota_bytes": 100,
        }),
    )
    monkeypatch.setattr(al_api.svc, "total_used_bytes", MagicMock(return_value=40))
    monkeypatch.setattr(
        al_api.svc.AssetLibraryQuotaModel, "is_enabled",
        MagicMock(return_value=True),
    )
    resp = client.get("/api/asset-library/status", headers=AUTH)
    data = resp.json()["data"]
    assert data["enabled"] is True
    assert data["allowed"] is True
    assert data["used_bytes"] == 40


def test_status_denied_when_not_whitelisted(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        al_api.svc, "get_feature_config",
        MagicMock(return_value={
            "enabled": True, "allow_all_users": False,
            "total_quota_bytes": 100,
        }),
    )
    monkeypatch.setattr(
        al_api.svc.AssetLibraryQuotaModel, "is_enabled",
        MagicMock(return_value=False),
    )
    # used_bytes 为全站统计，只受总开关控制，与个人 allowed 无关
    monkeypatch.setattr(al_api.svc, "total_used_bytes", MagicMock(return_value=40))
    resp = client.get("/api/asset-library/status", headers=AUTH)
    data = resp.json()["data"]
    assert data["allowed"] is False
    assert data["used_bytes"] == 40


def test_status_allowed_for_admin_without_whitelist(monkeypatch):
    client = _client(monkeypatch, role="admin")
    monkeypatch.setattr(
        al_api.svc, "get_feature_config",
        MagicMock(return_value={
            "enabled": True, "allow_all_users": False,
            "total_quota_bytes": 100,
        }),
    )
    monkeypatch.setattr(al_api.svc, "total_used_bytes", MagicMock(return_value=1))
    monkeypatch.setattr(
        al_api.svc.AssetLibraryQuotaModel, "is_enabled",
        MagicMock(return_value=False),
    )
    resp = client.get("/api/asset-library/status", headers=AUTH)
    assert resp.json()["data"]["allowed"] is True


def test_search_users_passthrough(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        al_api.svc, "search_user_exact",
        MagicMock(return_value={"user_id": 42, "display_name": "张三"}),
    )
    resp = client.get(
        "/api/asset-library/users",
        params={"account": "13800000000"}, headers=AUTH)
    assert resp.json()["data"]["user"]["user_id"] == 42
