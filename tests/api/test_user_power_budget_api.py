"""用户单次算力上限路由（/api/user/power-budget GET/PUT/DELETE）回归测试。

背景：该路由曾在商业版漏挂（fix 796d6db2「商业版补挂 /api/user/power-budget
路由，保存失败前端可见」），属热修复回归点，路由层此前零测试（模块层纯函数
已有 tests/script_writer_core/test_power_budget.py 覆盖）。

覆盖：
- GET 返回 {limit, is_custom, default_limit} 三元组
- PUT 非法 limit（负数/非整数语义）→ 400 且不落库
- PUT 合法值（含 0=不限制）→ upsert 落库并返回 is_custom=True
- DELETE → 删除偏好，payload 回退平台默认
- 未带 token → 401
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api import user as user_api
from config.constant import PREF_WORLD_ID_GLOBAL
from model.user_preferences import PREF_TYPE_POWER_BUDGET
from script_writer_core.agents import power_budget as pb


def _mock_auth(monkeypatch, user_id=123):
    monkeypatch.setattr(user_api, "_require_user_id", lambda token: user_id)


def _mock_resolution(monkeypatch, limit, is_custom, default=30):
    monkeypatch.setattr(pb, "resolve_user_power_budget", lambda uid: (limit, is_custom))
    monkeypatch.setattr(pb, "_resolve_platform_default", lambda: default)


def test_get_power_budget_returns_payload(monkeypatch):
    _mock_auth(monkeypatch)
    _mock_resolution(monkeypatch, limit=50, is_custom=True, default=30)
    result = asyncio.run(user_api.get_power_budget(auth_token="Bearer t"))
    assert result["code"] == 0
    assert result["data"] == {"limit": 50, "is_custom": True, "default_limit": 30}


def test_get_power_budget_defaults_when_no_pref(monkeypatch):
    _mock_auth(monkeypatch)
    _mock_resolution(monkeypatch, limit=30, is_custom=False, default=30)
    result = asyncio.run(user_api.get_power_budget(auth_token="Bearer t"))
    assert result["data"] == {"limit": 30, "is_custom": False, "default_limit": 30}


def test_put_power_budget_rejects_negative(monkeypatch):
    _mock_auth(monkeypatch)
    prefs = MagicMock()
    monkeypatch.setattr(user_api, "UserPreferencesModel", prefs)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(user_api.set_power_budget(
            request=_BudgetRequest(limit=-1), auth_token="Bearer t"))
    assert exc_info.value.status_code == 400
    prefs.upsert.assert_not_called()


def test_put_power_budget_rejects_bool_like_true(monkeypatch):
    # validate 走 _try_parse_non_negative_int，True 不是合法整数值语义
    _mock_auth(monkeypatch)
    prefs = MagicMock()
    monkeypatch.setattr(user_api, "UserPreferencesModel", prefs)
    with pytest.raises(HTTPException):
        asyncio.run(user_api.set_power_budget(
            request=_BudgetRequest(limit=True), auth_token="Bearer t"))
    prefs.upsert.assert_not_called()


def test_put_power_budget_persists_and_returns_custom(monkeypatch):
    _mock_auth(monkeypatch, user_id=7)
    _mock_resolution(monkeypatch, limit=88, is_custom=True, default=30)
    prefs = MagicMock()
    monkeypatch.setattr(user_api, "UserPreferencesModel", prefs)

    result = asyncio.run(user_api.set_power_budget(
        request=_BudgetRequest(limit=88), auth_token="Bearer t"))

    prefs.upsert.assert_called_once_with(
        "7", PREF_WORLD_ID_GLOBAL, PREF_TYPE_POWER_BUDGET, {"limit": 88})
    assert result["data"]["limit"] == 88
    assert result["data"]["is_custom"] is True
    assert result["data"]["default_limit"] == 30


def test_put_power_budget_accepts_zero_as_unlimited(monkeypatch):
    _mock_auth(monkeypatch)
    _mock_resolution(monkeypatch, limit=0, is_custom=True, default=30)
    prefs = MagicMock()
    monkeypatch.setattr(user_api, "UserPreferencesModel", prefs)

    result = asyncio.run(user_api.set_power_budget(
        request=_BudgetRequest(limit=0), auth_token="Bearer t"))

    prefs.upsert.assert_called_once()
    assert result["data"]["limit"] == 0
    assert result["data"]["is_custom"] is True


def test_delete_power_budget_falls_back_to_default(monkeypatch):
    _mock_auth(monkeypatch, user_id=9)
    _mock_resolution(monkeypatch, limit=30, is_custom=False, default=30)
    prefs = MagicMock()
    monkeypatch.setattr(user_api, "UserPreferencesModel", prefs)

    result = asyncio.run(user_api.delete_power_budget(auth_token="Bearer t"))

    prefs.delete.assert_called_once_with(
        "9", PREF_WORLD_ID_GLOBAL, PREF_TYPE_POWER_BUDGET)
    assert result["data"] == {"limit": 30, "is_custom": False, "default_limit": 30}


def test_power_budget_requires_auth(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(user_api.get_power_budget(auth_token=None))
    assert exc_info.value.status_code == 401


class _BudgetRequest:
    """与 api.user.PowerBudgetRequest 同形状的最小请求对象。"""

    def __init__(self, limit):
        self.limit = limit
