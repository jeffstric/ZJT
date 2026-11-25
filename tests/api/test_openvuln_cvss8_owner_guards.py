"""安全审计 BUG-R2-S1-A1-H3/H4/H5 + A9-H1：跨租户越权端点属主断言测试。

统一样板（同 tests/api/test_latest_task_owner.py）：monkeypatch token 解析 +
模型静态方法，把路由函数挂到独立 FastAPI app，TestClient 验证
非属主请求一律 403/404（防枚举），不再触达数据层。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import script_writer
from model.user_tokens import UserTokensModel


class _EntityStub:
    """ChatSessionsModel.get_by_session_id 的最小实体。"""

    def __init__(self, user_id, session_type=1):
        self.session_id = 's-1'
        self.user_id = user_id
        self.session_type = session_type


def _auth():
    return {'Authorization': 'Bearer valid-token'}


def _token(monkeypatch, token_user_id=7):
    monkeypatch.setattr(
        UserTokensModel,
        'get_user_id_by_token',
        staticmethod(lambda token: token_user_id if token == 'valid-token' else None),
    )


# ==================== A1-H4：chat-session 管理四端点 ====================

def _session_client(monkeypatch, entity, token_user_id=7):
    _token(monkeypatch, token_user_id)
    monkeypatch.setattr(
        'model.chat_sessions.ChatSessionsModel.get_by_session_id',
        staticmethod(lambda session_id: entity),
    )
    monkeypatch.setattr(
        'model.chat_sessions.ChatSessionsModel.soft_delete',
        staticmethod(lambda session_id, session_type=None: 1),
    )
    monkeypatch.setattr(
        'model.chat_sessions.ChatSessionsModel.update_title',
        staticmethod(lambda session_id, title: 1),
    )
    monkeypatch.setattr(
        'model.chat_messages.ChatMessagesModel.update_content',
        staticmethod(lambda message_id, content, message_type, session_id: 1),
    )
    app = FastAPI()
    app.put('/api/session/{session_id}/message/{message_id}')(script_writer.update_message_content)
    app.delete('/api/session/{session_id}')(script_writer.delete_session)
    app.put('/api/session/{session_id}/title')(script_writer.update_session_title)
    return TestClient(app)


def test_update_message_content_foreign_session_404(monkeypatch):
    """他人会话的消息更新 → 404（防枚举）"""
    client = _session_client(monkeypatch, entity=_EntityStub(user_id=2))
    resp = client.put(
        '/api/session/s-1/message/m-1',
        headers=_auth(), json={'content': 'tampered'},
    )
    assert resp.status_code == 404


def test_delete_session_foreign_session_404(monkeypatch):
    client = _session_client(monkeypatch, entity=_EntityStub(user_id=2))
    resp = client.delete('/api/session/s-1', headers=_auth())
    assert resp.status_code == 404


def test_update_session_title_foreign_session_404(monkeypatch):
    client = _session_client(monkeypatch, entity=_EntityStub(user_id=2))
    resp = client.put(
        '/api/session/s-1/title', headers=_auth(), json={'title': 'poisoned'},
    )
    assert resp.status_code == 404


def test_delete_and_rename_own_session_ok(monkeypatch):
    client = _session_client(monkeypatch, entity=_EntityStub(user_id=7))
    resp = client.delete('/api/session/s-1', headers=_auth())
    assert resp.status_code == 200 and resp.json()['success'] is True
    resp = client.put(
        '/api/session/s-1/title', headers=_auth(), json={'title': 'new title'},
    )
    assert resp.status_code == 200 and resp.json()['success'] is True


def test_session_endpoints_missing_session_404(monkeypatch):
    """会话不存在 → 404（不暴露存在性）"""
    client = _session_client(monkeypatch, entity=None)
    resp = client.delete('/api/session/s-1', headers=_auth())
    assert resp.status_code == 404


# ==================== A1-H5：skills 四端点身份一致性 ====================

def _skills_client(monkeypatch):
    _token(monkeypatch)

    class _LoaderStub:
        skills_dir = None

        def get_all_skills_metadata(self):
            return {}

        def list_skills(self):
            return []

    monkeypatch.setattr(script_writer, 'SkillLoader', _LoaderStub)
    app = FastAPI()
    app.get('/api/skills')(script_writer.list_skills)
    app.get('/api/skills/{skill_name}')(script_writer.get_skill_detail)
    app.put('/api/skills/{skill_name}')(script_writer.update_skill)
    app.delete('/api/skills/{skill_name}')(script_writer.delete_skill)
    return TestClient(app)


@pytest.mark.parametrize('method,path', [
    ('get', '/api/skills'),
    ('get', '/api/skills/writer'),
    ('put', '/api/skills/writer'),
    ('delete', '/api/skills/writer'),
])
def test_skills_family_rejects_foreign_user_id(monkeypatch, method, path):
    """user_id 查询参数与登录身份不一致 → 403（跨租户读写删全堵）"""
    client = _skills_client(monkeypatch)
    kwargs = {'headers': _auth(), 'params': {'user_id': 2}}
    if method == 'put':
        kwargs['json'] = {'prompt_content': 'poisoned prompt'}
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 403


# ==================== A1-H3：import-world 两端点 ====================

def test_import_world_from_cloud_rejects_mismatched_user(monkeypatch):
    """自报 user_id 与登录身份不一致 → 403"""
    _token(monkeypatch)
    app = FastAPI()
    app.post('/api/import-world-from-cloud')(script_writer.import_world_from_cloud)
    client = TestClient(app)
    resp = client.post(
        '/api/import-world-from-cloud',
        headers=_auth(),
        data={'user_id': '2', 'world_id': '3', 'key': 'world_import/2026/x.zip'},
    )
    assert resp.status_code == 403


def test_import_world_from_cloud_rejects_foreign_bucket_key(monkeypatch):
    """key 不带 world_import/ 前缀 → 400（不得对共享桶任意对象签发下载）"""
    _token(monkeypatch)
    app = FastAPI()
    app.post('/api/import-world-from-cloud')(script_writer.import_world_from_cloud)
    client = TestClient(app)
    resp = client.post(
        '/api/import-world-from-cloud',
        headers=_auth(),
        data={'user_id': '7', 'world_id': '3', 'key': 'other-prefix/x.zip'},
    )
    assert resp.status_code == 400


def test_import_world_rejects_mismatched_user(monkeypatch):
    """zip 导入链路同样拒绝自报 user_id 不一致"""
    _token(monkeypatch)
    app = FastAPI()
    app.post('/api/import-world')(script_writer.import_world)
    client = TestClient(app)
    resp = client.post(
        '/api/import-world',
        headers=_auth(),
        data={'user_id': '2', 'world_id': '3'},
        files={'file': ('w.zip', b'PK\x03\x04', 'application/zip')},
    )
    assert resp.status_code == 403


# ==================== A9-H1：update_character / update_location ====================

class _AssetStub:
    def __init__(self, user_id):
        self.user_id = user_id
        self.world_id = 1


def _asset_client(monkeypatch, character=None, location=None):
    _token(monkeypatch)
    import server

    monkeypatch.setattr('server.CharacterModel.get_by_id', staticmethod(lambda cid: character))
    monkeypatch.setattr('server.LocationModel.get_by_id', staticmethod(lambda lid: location))
    app = FastAPI()
    app.post('/api/characters/update')(server.update_character)
    app.put('/api/locations/{location_id}')(server.update_location)
    return TestClient(app)


def test_update_character_foreign_owner_403(monkeypatch):
    """任意登录租户覆写他人 character → 403"""
    client = _asset_client(monkeypatch, character=_AssetStub(user_id=2))
    resp = client.post(
        '/api/characters/update',
        headers={**_auth(), 'X-User-Id': '7'},
        data={'character_id': '1', 'name': 'hijacked'},
    )
    assert resp.status_code == 403


def test_update_character_missing_404(monkeypatch):
    client = _asset_client(monkeypatch, character=None)
    resp = client.post(
        '/api/characters/update',
        headers={**_auth(), 'X-User-Id': '7'},
        data={'character_id': '1', 'name': 'x'},
    )
    assert resp.status_code == 404


def test_update_location_foreign_owner_403(monkeypatch):
    """任意登录租户覆写他人 location → 403"""
    client = _asset_client(monkeypatch, location=_AssetStub(user_id=2))
    resp = client.put(
        '/api/locations/1',
        headers={**_auth(), 'X-User-Id': '7'},
        data={'name': 'hijacked'},
    )
    assert resp.status_code == 403
