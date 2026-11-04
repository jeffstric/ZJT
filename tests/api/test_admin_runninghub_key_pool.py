"""RH 密钥池管理 API 的 key_type 参数校验回归测试。

覆盖 admin_set_runninghub_key 端点直调路径：
  - 缺失请求体（request=None）→ 400（而非未处理 AttributeError 裸 500）
  - key_type 非法取值 → 400
  - 合法 key_type / 省略 key_type 透传给 set_key_async
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api import admin as admin_api
from api.admin import RunningHubKeyRequest


@pytest.fixture
def authed_admin(monkeypatch):
    """绕过鉴权与商业门禁，直测端点逻辑（门禁行为由 commercial_gates 专项覆盖）。"""
    async def fake_admin(token):
        return SimpleNamespace(id=7)

    monkeypatch.setattr(admin_api, "require_admin", fake_admin)
    monkeypatch.setattr(admin_api, "_require_enterprise_for_key_pool", lambda: None)
    return fake_admin


def _async_return(value):
    fut = asyncio.Future()
    fut.set_result(value)
    return fut


def test_missing_body_returns_400_not_crash(authed_admin):
    """PUT 不带请求体（request=None）必须 400，不能未处理 AttributeError。"""
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(admin_api.admin_set_runninghub_key(1, None, "token"))
    assert exc_info.value.status_code == 400
    assert "请求体不能为空" in str(exc_info.value.detail)


def test_invalid_key_type_rejected(authed_admin):
    request = RunningHubKeyRequest(key_type='premium')
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(admin_api.admin_set_runninghub_key(1, request, "token"))
    assert exc_info.value.status_code == 400
    assert "key_type" in str(exc_info.value.detail)


@pytest.mark.parametrize("key_type", ["standard", "wallet"])
def test_valid_key_type_passed_through(authed_admin, key_type):
    request = RunningHubKeyRequest(key_type=key_type)
    captured = {}

    async def fake_set_key_async(index, **kwargs):
        captured.update(kwargs, _index=index)
        return ['key_type']

    with patch('task.runninghub_key_pool.set_key_async', fake_set_key_async):
        result = asyncio.run(admin_api.admin_set_runninghub_key(1, request, "token"))

    assert result["code"] == 0
    assert captured['key_type'] == key_type
    assert captured['_index'] == 1
    assert captured['updated_by'] == 7


def test_omitted_key_type_passes_none(authed_admin):
    """不传 key_type 时透传 None（后端不写该字段，保持原值）。"""
    request = RunningHubKeyRequest(max_slots=5)
    captured = {}

    async def fake_set_key_async(index, **kwargs):
        captured.update(kwargs)
        return ['max_slots']

    with patch('task.runninghub_key_pool.set_key_async', fake_set_key_async):
        asyncio.run(admin_api.admin_set_runninghub_key(2, request, "token"))

    assert captured['key_type'] is None
    assert captured['max_slots'] == 5
