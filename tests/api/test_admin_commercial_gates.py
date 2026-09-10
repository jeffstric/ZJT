"""商业版管理端功能的许可证门禁回归测试。

覆盖 commercial.base 能力（RH 密钥池 / 供应商自动切换）的 403 守卫：
商业部署但许可证未激活时必须拒绝，不能只按部署形态（社区/商业）放行。
"""

import asyncio
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import admin as admin_api


def _inject_enterprise_runtime(monkeypatch, allowed: bool) -> None:
    """把伪 enterprise 许可证运行时注入 sys.modules，模拟商业部署激活态。"""
    fake = SimpleNamespace(
        is_commercial_license_allowed=lambda: allowed,
        is_commercial_license_strictly_allowed=lambda: allowed,
    )
    monkeypatch.setitem(sys.modules, "enterprise.services.license.runtime", fake)


# ---------------------------------------------------------------------------
# _is_commercial_base_license_active：enterprise 缺席 / 运行时判定
# ---------------------------------------------------------------------------


def test_commercial_base_helper_fail_closed_without_enterprise(monkeypatch):
    monkeypatch.setitem(sys.modules, "enterprise.services.license.runtime", None)
    assert admin_api._is_commercial_base_license_active() is False


@pytest.mark.parametrize("allowed", [True, False])
def test_commercial_base_helper_reflects_license_runtime(monkeypatch, allowed):
    _inject_enterprise_runtime(monkeypatch, allowed)
    assert admin_api._is_commercial_base_license_active() is allowed


# ---------------------------------------------------------------------------
# _require_enterprise_for_key_pool：Provider 注册 + 许可证激活双条件
# ---------------------------------------------------------------------------


def test_key_pool_guard_rejects_when_provider_missing(monkeypatch):
    monkeypatch.setattr("task.runninghub_key_pool.is_available", lambda: False)
    with pytest.raises(HTTPException) as exc_info:
        admin_api._require_enterprise_for_key_pool()
    assert exc_info.value.status_code == 403
    assert "此功能仅商业版本可用" in str(exc_info.value.detail)


def test_key_pool_guard_rejects_when_license_inactive(monkeypatch):
    """商业部署（Provider 已注册）但许可证未激活：同样 403。"""
    monkeypatch.setattr("task.runninghub_key_pool.is_available", lambda: True)
    monkeypatch.setattr(
        admin_api, "_is_commercial_base_license_active", lambda: False
    )
    with pytest.raises(HTTPException) as exc_info:
        admin_api._require_enterprise_for_key_pool()
    assert exc_info.value.status_code == 403
    assert "激活商业许可证" in str(exc_info.value.detail)


def test_key_pool_guard_passes_when_licensed(monkeypatch):
    monkeypatch.setattr("task.runninghub_key_pool.is_available", lambda: True)
    monkeypatch.setattr(
        admin_api, "_is_commercial_base_license_active", lambda: True
    )
    admin_api._require_enterprise_for_key_pool()


# ---------------------------------------------------------------------------
# /api/admin/retry-global-enabled：供应商自动切换总开关
# ---------------------------------------------------------------------------


def _run_retry_global(monkeypatch, *, community: bool, licensed: bool):
    async def _fake_require_admin(_auth_token):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(admin_api, "require_admin", _fake_require_admin)
    monkeypatch.setattr(
        "config.strategy.edition_strategy.IS_COMMUNITY_EDITION", community
    )
    monkeypatch.setattr(
        admin_api, "_is_commercial_base_license_active", lambda: licensed
    )
    return asyncio.run(
        admin_api.admin_update_retry_global_enabled(
            admin_api.RetryGlobalEnabledRequest(enabled=True),
            auth_token="Bearer x",
        )
    )


def test_retry_global_rejects_unlicensed_commercial(monkeypatch):
    """商业部署 + 未激活许可证：必须 403，不得写配置。"""
    with pytest.raises(HTTPException) as exc_info:
        _run_retry_global(monkeypatch, community=False, licensed=False)
    assert exc_info.value.status_code == 403
    assert "激活商业许可证" in str(exc_info.value.detail)


def test_retry_global_rejects_community(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        _run_retry_global(monkeypatch, community=True, licensed=True)
    assert exc_info.value.status_code == 403


def test_retry_global_passes_when_licensed(monkeypatch):
    writes = []

    def _fake_write(*args, **kwargs):
        writes.append((args, kwargs))

    monkeypatch.setattr("config.config_util.set_dynamic_config_value", _fake_write)
    result = _run_retry_global(monkeypatch, community=False, licensed=True)
    assert result["code"] == 0
    assert writes, "已激活态应真正写入开关配置"
