"""统一鉴权修复的单测。

覆盖：
- require_permission 装饰器真实现（无 token 401 / 无效 token 401 / 有效 token 注入 state / query 兜底）
- perseids_server/utils/auth_identity.py 的属主断言辅助（ensure_owner / check_claimed_user_id）
"""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from perseids_server.utils.auth_identity import (
    check_claimed_user_id,
    ensure_owner,
    get_auth_user_id,
)
from perseids_server.utils.permission import require_permission


def _client(monkeypatch, token_user_id=1):
    """构造挂了 require_permission 的最小 app，token 解析结果可控。"""
    from model.user_tokens import UserTokensModel

    monkeypatch.setattr(
        UserTokensModel, 'get_user_id_by_token',
        staticmethod(lambda token: token_user_id if token == 'valid-token' else None),
    )

    app = FastAPI()

    @app.get('/protected')
    @require_permission("test:view")
    async def protected(request: Request):
        return {'user_id': get_auth_user_id(request)}

    return TestClient(app)


def test_missing_token_rejected(monkeypatch):
    resp = _client(monkeypatch).get('/protected')
    assert resp.status_code == 401
    assert resp.json()['error_code'] == 'missing_auth_token'


def test_invalid_token_rejected(monkeypatch):
    resp = _client(monkeypatch).get(
        '/protected', headers={'Authorization': 'Bearer wrong-token'}
    )
    assert resp.status_code == 401
    assert resp.json()['error_code'] == 'invalid_auth_token'


def test_valid_token_injects_user_id(monkeypatch):
    resp = _client(monkeypatch).get(
        '/protected', headers={'Authorization': 'Bearer valid-token'}
    )
    assert resp.status_code == 200
    assert resp.json()['user_id'] == 1


def test_bare_token_without_bearer_prefix_accepted(monkeypatch):
    """兼容存量前端裸 token 写法"""
    resp = _client(monkeypatch).get(
        '/protected', headers={'Authorization': 'valid-token'}
    )
    assert resp.status_code == 200
    assert resp.json()['user_id'] == 1


def test_query_auth_token_fallback(monkeypatch):
    """兼容存量前端 query 传 token（校验强度与 header 一致）"""
    resp = _client(monkeypatch).get('/protected?auth_token=valid-token')
    assert resp.status_code == 200
    assert resp.json()['user_id'] == 1


def test_query_auth_token_invalid_still_rejected(monkeypatch):
    resp = _client(monkeypatch).get('/protected?auth_token=wrong-token')
    assert resp.status_code == 401


# ==================== 属主断言辅助 ====================

def test_ensure_owner_accepts_matching_ids_across_types():
    """str/int 归一化比较（agent_tasks 是 varchar，ai_tools 是 int）"""
    assert ensure_owner('123', 123) is None
    assert ensure_owner(123, '123') is None
    assert ensure_owner(' 123 ', 123) is None


def test_ensure_owner_rejects_mismatch_with_404():
    resp = ensure_owner('999', 1)
    assert resp is not None
    assert resp.status_code == 404


def test_ensure_owner_rejects_missing_entity_user():
    """资源无属主信息时不放行"""
    assert ensure_owner(None, 1) is not None


def test_check_claimed_user_id_allows_empty_claim():
    assert check_claimed_user_id(None, 1) is None
    assert check_claimed_user_id('', 1) is None


def test_check_claimed_user_id_mismatch_returns_403():
    resp = check_claimed_user_id('2', 1)
    assert resp is not None
    assert resp.status_code == 403


def test_check_claimed_user_id_match_passes():
    assert check_claimed_user_id('1', 1) is None
    assert check_claimed_user_id(1, '1') is None
