"""GET /api/sessions 鉴权收紧的单测（2026-10-12 课堂跨用户会话事故修复）。

覆盖：
- 未登录 → 401
- user_id 与登录身份不一致 → 403（不再把他人会话列表泄露给调用方）
- user_id 与登录身份一致 → 200
- 无 user_id 的调试路径仅限管理员（普通登录用户 403）
- SessionCreateRequest.user_id 可省略（以登录身份为准，前端自愈建会话依赖此语义）
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import script_writer
from model.chat_sessions import ChatSessionsModel
from model.user_tokens import UserTokensModel
from model.users import UsersModel


def _client(monkeypatch, token_user_id=7, admin_role=False):
    """构造挂载真实 list_sessions 的最小 app，token 解析与用户角色可控。"""
    monkeypatch.setattr(
        UserTokensModel, 'get_user_id_by_token',
        staticmethod(lambda token: token_user_id if token == 'valid-token' else None),
    )
    if admin_role:
        admin_user = type('UserStub', (), {'role': 'admin'})
        monkeypatch.setattr(UsersModel, 'get_by_id', staticmethod(lambda uid: admin_user))
    else:
        monkeypatch.setattr(UsersModel, 'get_by_id', staticmethod(lambda uid: None))

    app = FastAPI()
    app.get('/api/sessions')(script_writer.list_sessions)
    return TestClient(app)


def test_sessions_missing_token_rejected(monkeypatch):
    resp = _client(monkeypatch).get('/api/sessions')
    assert resp.status_code == 401


def test_sessions_user_id_mismatch_rejected(monkeypatch):
    """查询参数 user_id 是他人时一律 403，不得返回其会话列表（事故根因）"""
    monkeypatch.setattr(
        ChatSessionsModel, 'list_by_user',
        staticmethod(lambda *a, **k: pytest.fail('身份不一致时不应触达数据库')),
    )
    resp = _client(monkeypatch, token_user_id=7).get(
        '/api/sessions',
        params={'user_id': '2'},
        headers={'Authorization': 'Bearer valid-token'},
    )
    assert resp.status_code == 403
    assert resp.json()['success'] is False


def test_sessions_own_user_id_allowed(monkeypatch):
    monkeypatch.setattr(
        ChatSessionsModel, 'list_by_user',
        staticmethod(lambda *a, **k: []),
    )
    resp = _client(monkeypatch, token_user_id=7).get(
        '/api/sessions',
        params={'user_id': '7'},
        headers={'Authorization': 'Bearer valid-token'},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data['success'] is True
    assert data['sessions'] == []


def test_sessions_debug_path_requires_admin(monkeypatch):
    """无 user_id 的调试路径会列出全部缓存会话，普通登录用户不可用"""
    resp = _client(monkeypatch, token_user_id=7).get(
        '/api/sessions',
        headers={'Authorization': 'Bearer valid-token'},
    )
    assert resp.status_code == 403


def test_sessions_debug_path_admin_allowed(monkeypatch):
    resp = _client(monkeypatch, token_user_id=7, admin_role=True).get(
        '/api/sessions',
        headers={'Authorization': 'Bearer valid-token'},
    )
    assert resp.status_code == 200
    assert resp.json()['sessions'] == []


def test_session_create_request_user_id_optional():
    """前端自愈建会话不再回传 user_id，模型必须允许缺省（缺省以登录身份为准）"""
    req = script_writer.SessionCreateRequest(world_id='1')
    assert req.user_id is None
