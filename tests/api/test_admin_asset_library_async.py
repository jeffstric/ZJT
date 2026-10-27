"""资产库管理端点的同步数据库调用必须经 asyncio.to_thread 卸载。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from api import admin as admin_api
from config import config_util
from model.asset_library_quota import AssetLibraryQuotaModel
from model.system_config import SystemConfigModel
from services import asset_library_service as asset_svc


def _mock_admin_and_user(monkeypatch):
    async def fake_require_admin(auth_token):
        return SimpleNamespace(id=1, role="admin")

    monkeypatch.setattr(admin_api, "require_admin", fake_require_admin)
    users_model = MagicMock()
    users_model.get_by_id.return_value = SimpleNamespace(id=2)
    monkeypatch.setattr(admin_api, "UsersModel", users_model)
    return users_model


def _record_to_thread(monkeypatch):
    calls = []

    async def fake_to_thread(func, /, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(admin_api.asyncio, "to_thread", fake_to_thread)
    return calls


def test_get_config_offloads_sync_calls(monkeypatch):
    _mock_admin_and_user(monkeypatch)
    calls = _record_to_thread(monkeypatch)
    monkeypatch.setattr(asset_svc, "get_feature_config", MagicMock(return_value={
        "enabled": True,
        "allow_all_users": False,
        "total_quota_bytes": 1024 ** 3,
    }))
    monkeypatch.setattr(asset_svc, "total_used_bytes", MagicMock(return_value=128))

    result = asyncio.run(admin_api.admin_get_asset_library_config("Bearer test"))

    assert result["data"]["used_bytes"] == 128
    assert calls == [asset_svc.get_feature_config, asset_svc.total_used_bytes]


def test_set_config_offloads_upsert_and_cache_invalidation(monkeypatch):
    _mock_admin_and_user(monkeypatch)
    calls = _record_to_thread(monkeypatch)
    monkeypatch.setattr(SystemConfigModel, "upsert", MagicMock())
    monkeypatch.setattr(config_util, "invalidate_dynamic_cache", MagicMock())
    request = SimpleNamespace(enabled=True, allow_all_users=True, total_quota_gb=1.0)

    result = asyncio.run(admin_api.admin_set_asset_library_config(request, "Bearer test"))

    assert result["code"] == 0
    assert len(calls) == 6
    assert calls[0::2] == [SystemConfigModel.upsert] * 3
    assert calls[1::2] == [config_util.invalidate_dynamic_cache] * 3


def test_set_permission_offloads_sync_calls(monkeypatch):
    users_model = _mock_admin_and_user(monkeypatch)
    calls = _record_to_thread(monkeypatch)
    monkeypatch.setattr(AssetLibraryQuotaModel, "set_enabled", MagicMock())
    request = SimpleNamespace(enabled=True)

    result = asyncio.run(admin_api.admin_set_user_asset_permission(2, request, "Bearer test"))

    assert result["data"]["enabled"] is True
    assert calls == [users_model.get_by_id, AssetLibraryQuotaModel.set_enabled]


def test_get_user_quota_offloads_sync_calls(monkeypatch):
    users_model = _mock_admin_and_user(monkeypatch)
    calls = _record_to_thread(monkeypatch)
    monkeypatch.setattr(asset_svc, "get_quota", MagicMock(return_value={
        "quota_bytes": 1024,
        "used_bytes": 128,
    }))
    monkeypatch.setattr(asset_svc, "list_user_assets_for_admin", MagicMock(return_value={"total": 3}))
    monkeypatch.setattr(AssetLibraryQuotaModel, "is_enabled", MagicMock(return_value=True))

    result = asyncio.run(admin_api.admin_get_user_asset_quota(2, "Bearer test"))

    assert result["data"]["asset_count"] == 3
    assert calls == [
        users_model.get_by_id,
        asset_svc.get_quota,
        asset_svc.list_user_assets_for_admin,
        AssetLibraryQuotaModel.is_enabled,
    ]


def test_set_user_quota_offloads_sync_calls(monkeypatch):
    users_model = _mock_admin_and_user(monkeypatch)
    calls = _record_to_thread(monkeypatch)
    monkeypatch.setattr(AssetLibraryQuotaModel, "get_by_user", MagicMock(side_effect=[
        {"quota_bytes": 1024},
        {"quota_bytes": 2048, "used_bytes": 128},
    ]))
    monkeypatch.setattr(AssetLibraryQuotaModel, "set_quota", MagicMock())
    request = SimpleNamespace(quota_bytes=2048)

    result = asyncio.run(admin_api.admin_set_user_asset_quota(2, request, "Bearer test"))

    assert result["data"]["new_quota_bytes"] == 2048
    assert calls == [
        users_model.get_by_id,
        AssetLibraryQuotaModel.get_by_user,
        AssetLibraryQuotaModel.set_quota,
        AssetLibraryQuotaModel.get_by_user,
    ]


def test_list_user_assets_offloads_sync_calls(monkeypatch):
    users_model = _mock_admin_and_user(monkeypatch)
    calls = _record_to_thread(monkeypatch)
    monkeypatch.setattr(
        asset_svc,
        "list_user_assets_for_admin",
        MagicMock(return_value={"total": 0, "items": []}),
    )

    result = asyncio.run(admin_api.admin_list_user_assets(2, 1, 50, "Bearer test"))

    assert result["data"]["total"] == 0
    assert calls == [users_model.get_by_id, asset_svc.list_user_assets_for_admin]
