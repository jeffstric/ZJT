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


# ==================== verify_auth_token（本地强校验） ====================

def test_verify_auth_token_empty_token_rejected():
    """安全修复：空 token 不再放行，一律拒绝"""
    ok, resp = _run(script_writer.verify_auth_token("1", ""))
    assert ok is False
    assert resp['error_code'] == ERROR_CODE_TOKEN_EXPIRED
    assert resp['token_expired'] is True


def test_verify_auth_token_invalid_token_is_expired(monkeypatch):
    monkeypatch.setattr(
        script_writer.UserTokensModel, 'get_user_id_by_token',
        staticmethod(lambda token: None),
    )

    ok, resp = _run(script_writer.verify_auth_token("1", "tok"))
    assert ok is False
    assert resp['error_code'] == ERROR_CODE_TOKEN_EXPIRED
    assert resp['token_expired'] is True


def test_verify_auth_token_owner_mismatch_rejected(monkeypatch):
    """安全修复：token 属主与声明 user_id 不一致必须拒绝（原实现仅查 user 是否有 token）"""
    monkeypatch.setattr(
        script_writer.UserTokensModel, 'get_user_id_by_token',
        staticmethod(lambda token: 999),
    )

    ok, resp = _run(script_writer.verify_auth_token("1", "tok-of-user-999"))
    assert ok is False
    assert resp['error_code'] == ERROR_CODE_TOKEN_EXPIRED


def test_verify_auth_token_owner_match_passes(monkeypatch):
    monkeypatch.setattr(
        script_writer.UserTokensModel, 'get_user_id_by_token',
        staticmethod(lambda token: 1),
    )

    ok, resp = _run(script_writer.verify_auth_token("1", "tok-of-user-1"))
    assert ok is True
    assert resp is None


def test_verify_auth_token_db_failure_is_service_unavailable(monkeypatch):
    """本地 DB 异常视为服务不可用（502），不得误报 token 失效"""
    def boom(token):
        raise RuntimeError('db down')

    monkeypatch.setattr(script_writer.UserTokensModel, 'get_user_id_by_token',
                        staticmethod(boom))

    ok, resp = _run(script_writer.verify_auth_token("1", "tok"))
    assert ok is False
    assert resp['error_code'] == ERROR_CODE_AUTH_SERVICE_UNAVAILABLE
    assert 'token_expired' not in resp


class _DummyRequest:
    def __init__(self, authorization=""):
        self.headers = {"authorization": authorization}


def test_resolve_request_auth_token_header_wins_over_stale_session():
    """cookie 翻译后的 header 必须压过会话里已作废的旧 token。"""
    request = _DummyRequest("Bearer cookie-fresh")
    assert script_writer.resolve_request_auth_token(
        request, body_token="", session_token="stale-session-token"
    ) == "cookie-fresh"


def test_resolve_request_auth_token_empty_body_does_not_mask_header():
    request = _DummyRequest("Bearer cookie-fresh")
    assert script_writer.resolve_request_auth_token(
        request, body_token="", session_token=""
    ) == "cookie-fresh"


def test_resolve_request_auth_token_falls_back_to_session():
    request = _DummyRequest("Bearer ")
    assert script_writer.resolve_request_auth_token(
        request, body_token="", session_token="session-tok"
    ) == "session-tok"


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
