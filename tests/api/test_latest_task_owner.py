"""latest-task 端点属主断言与 auth_token 脱敏（审计 BUG-R2-S2-A8-H1）。

GET /api/session/{id}/latest-task 曾无属主检查直接返回 agent_tasks 行的
to_dict()——含任务属主的明文登录 token（唯一会话凭证），任何登录用户拿到
他人 session_id 即可完整接管其账号（admin 受害者可进一步读管理台密钥/
给自己提权）。修复：ensure_owner 属主断言（非本人 404 防枚举）+
to_dict 不再序列化 auth_token。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import script_writer
from model.user_tokens import UserTokensModel


class _TaskStub:
    def __init__(self, user_id, auth_token='PLAINTEXT-TOKEN-SHOULD-NOT-LEAK'):
        self.id = 1
        self.task_id = 't-1'
        self.session_id = 's-1'
        self.user_id = user_id
        self.world_id = None
        self.user_message = 'hello'
        self.auth_token = auth_token
        self.vendor_id = None
        self.model_id = None
        self.enable_thinking = False
        self.thinking_effort = None
        self.language = None
        self.execution_context_json = None
        self.image_urls = None
        self.video_urls = None
        self.audio_urls = None
        self.status = 'running'
        self.progress = 0
        self.current_step = None
        self.result = None
        self.error = None
        self.created_at = None
        self.started_at = None
        self.completed_at = None

    def to_dict(self):
        # 复用真实实体序列化，脱敏断言测的是生产实现而非本测试的仿制品
        from model.agent_tasks import AgentTaskEntity
        return AgentTaskEntity(**vars(self)).to_dict()


def _client(monkeypatch, token_user_id=7, task=None):
    monkeypatch.setattr(
        UserTokensModel, 'get_user_id_by_token',
        staticmethod(lambda token: token_user_id if token == 'valid-token' else None),
    )
    monkeypatch.setattr(
        'model.agent_tasks.AgentTasksModel.get_latest_by_session',
        staticmethod(lambda session_id: task),
    )
    app = FastAPI()
    app.get('/api/session/{session_id}/latest-task')(script_writer.get_latest_task_for_session)
    return TestClient(app)


def _auth():
    return {'Authorization': 'Bearer valid-token'}


def test_foreign_session_task_returns_404(monkeypatch):
    """他人会话的任务 → 404（ensure_owner 防枚举语义，不暴露存在性）"""
    client = _client(monkeypatch, token_user_id=7, task=_TaskStub(user_id=2))
    resp = client.get('/api/session/some-session/latest-task', headers=_auth())
    assert resp.status_code == 404


def test_own_session_task_ok_and_token_redacted(monkeypatch):
    """本人任务 → 200，且响应绝不包含明文 auth_token"""
    client = _client(monkeypatch, token_user_id=7, task=_TaskStub(user_id=7))
    resp = client.get('/api/session/some-session/latest-task', headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body['success'] is True
    assert 'auth_token' not in body['task']
    assert 'PLAINTEXT-TOKEN-SHOULD-NOT-LEAK' not in resp.text


def test_no_task_returns_404(monkeypatch):
    client = _client(monkeypatch, token_user_id=7, task=None)
    resp = client.get('/api/session/empty-session/latest-task', headers=_auth())
    assert resp.status_code == 404
    assert resp.json()['error'] == '没有任务'


def test_missing_token_rejected(monkeypatch):
    client = _client(monkeypatch, token_user_id=7, task=_TaskStub(user_id=7))
    resp = client.get('/api/session/some-session/latest-task')
    assert resp.status_code == 401
