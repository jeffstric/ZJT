"""登录 token 误失效修复的后端单测。

覆盖：
- api/script_writer.py 的 401 语义收紧（verify_auth_token / check_computing_power / _auth_error_status_code）
- perseids_server/client.py 的源头 error_code 打标与透传
"""
import asyncio

import pytest

from api import script_writer
from config.constant import (
    PERSEIDS_ERR_INVALID_AUTH_TOKEN,
    PERSEIDS_ERR_NO_VALID_TOKEN,
    ERROR_CODE_TOKEN_EXPIRED,
    ERROR_CODE_AUTH_SERVICE_UNAVAILABLE,
)
from perseids_server import client as perseids_client
from perseids_server.services.auth_service import AuthService


def _run(coro):
    return asyncio.run(coro)


# ==================== verify_auth_token ====================

def test_verify_auth_token_empty_token_passes():
    ok, resp = _run(script_writer.verify_auth_token("1", ""))
    assert ok is True
    assert resp is None


def test_verify_auth_token_no_valid_token_is_confirmed_expired(monkeypatch):
    async def fake_request(endpoint=None, data=None, method='POST', headers=None):
        return False, '未找到有效的token', {'error_code': PERSEIDS_ERR_NO_VALID_TOKEN}

    monkeypatch.setattr(script_writer, 'async_make_perseids_request', fake_request)

    ok, resp = _run(script_writer.verify_auth_token("1", "tok"))
    assert ok is False
    assert resp['error_code'] == ERROR_CODE_TOKEN_EXPIRED
    assert resp['token_expired'] is True


def test_verify_auth_token_service_failure_is_not_token_expired(monkeypatch):
    """无 error_code 的失败（服务故障）不得误报 token 失效"""
    async def fake_request(endpoint=None, data=None, method='POST', headers=None):
        return False, '查询token失败', {}

    monkeypatch.setattr(script_writer, 'async_make_perseids_request', fake_request)

    ok, resp = _run(script_writer.verify_auth_token("1", "tok"))
    assert ok is False
    assert resp['error_code'] == ERROR_CODE_AUTH_SERVICE_UNAVAILABLE
    assert 'token_expired' not in resp


def test_verify_auth_token_exception_is_service_unavailable(monkeypatch):
    async def fake_request(endpoint=None, data=None, method='POST', headers=None):
        raise RuntimeError('db down')

    monkeypatch.setattr(script_writer, 'async_make_perseids_request', fake_request)

    ok, resp = _run(script_writer.verify_auth_token("1", "tok"))
    assert ok is False
    assert resp['error_code'] == ERROR_CODE_AUTH_SERVICE_UNAVAILABLE


def test_auth_error_status_code_routing():
    assert script_writer._auth_error_status_code({'error_code': ERROR_CODE_AUTH_SERVICE_UNAVAILABLE}) == 502
    assert script_writer._auth_error_status_code({'error_code': ERROR_CODE_TOKEN_EXPIRED}) == 401
    assert script_writer._auth_error_status_code({}) == 401


# ==================== check_computing_power ====================

def test_check_computing_power_invalid_token_flagged(monkeypatch):
    async def fake_request(endpoint=None, data=None, method='POST', headers=None):
        return False, '无效的认证信息', {'error_code': PERSEIDS_ERR_INVALID_AUTH_TOKEN}

    monkeypatch.setattr(script_writer, 'async_make_perseids_request', fake_request)

    ok, power, err = _run(script_writer.check_computing_power("tok"))
    assert ok is False
    assert err.startswith('TOKEN_EXPIRED')


def test_check_computing_power_token_word_in_message_not_flagged(monkeypatch):
    """回归：错误消息含 'token'/'认证' 字样（如模型限额）不再被误判为登录失效"""
    async def fake_request(endpoint=None, data=None, method='POST', headers=None):
        return False, '模型 input_token 限额认证 exceeded', {}

    monkeypatch.setattr(script_writer, 'async_make_perseids_request', fake_request)

    ok, power, err = _run(script_writer.check_computing_power("tok"))
    assert ok is False
    assert 'TOKEN_EXPIRED' not in err


def test_check_computing_power_success(monkeypatch):
    async def fake_request(endpoint=None, data=None, method='POST', headers=None):
        return True, 'ok', {'computing_power': 42}

    monkeypatch.setattr(script_writer, 'async_make_perseids_request', fake_request)

    ok, power, err = _run(script_writer.check_computing_power("tok"))
    assert ok is True
    assert power == 42
    assert err is None


# ==================== perseids client 源头打标 ====================

def test_perseids_client_marks_invalid_token(monkeypatch):
    monkeypatch.setattr(AuthService, 'verify_token', staticmethod(lambda token: None))

    success, message, data = perseids_client.make_perseids_request(
        endpoint='user/check_computing_power',
        method='GET',
        headers={'Authorization': 'Bearer bad-token'},
    )
    assert success is False
    assert data.get('error_code') == PERSEIDS_ERR_INVALID_AUTH_TOKEN


def test_perseids_client_passthrough_no_valid_token(monkeypatch):
    monkeypatch.setattr(
        AuthService,
        'get_auth_token_by_user_id',
        staticmethod(lambda user_id: {
            "success": False,
            "message": "未找到有效的token",
            "error_code": PERSEIDS_ERR_NO_VALID_TOKEN,
        }),
    )

    success, message, data = perseids_client.make_perseids_request(
        endpoint='get_auth_token_by_user_id',
        data={'user_id': 1},
    )
    assert success is False
    assert data.get('error_code') == PERSEIDS_ERR_NO_VALID_TOKEN
