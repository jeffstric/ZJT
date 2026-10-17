"""DELETE /api/staging-file 不得再要求 query auth_token。

右侧暂存栏删除只带 Authorization 头。旧签名 auth_token: Query(...) 必填，
请求在进函数前就被 FastAPI 打成 422 Field required。
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import script_writer
from model.user_tokens import UserTokensModel


class _FakeFileManager:
    """避免测试里解析真实项目根目录或碰到用户暂存文件。"""

    def __init__(self, base_dir=None):
        self.base_dir = Path('G:/does-not-exist-staging-delete-test')


def _client(monkeypatch, token_user_id=7):
    monkeypatch.setattr(
        UserTokensModel, 'get_user_id_by_token',
        staticmethod(lambda token: token_user_id if token == 'valid-token' else None),
    )
    app = FastAPI()
    app.include_router(script_writer.router)
    return TestClient(app)


def _delete(client, headers=None, user_id='7', folder='scripts', filename='1.json'):
    return client.delete(
        '/api/staging-file',
        params={
            'user_id': user_id,
            'world_id': '3',
            'relative_path': f'{user_id}/3/{folder}/{filename}',
        },
        headers=headers or {},
    )


def _assert_not_query_token_422(resp):
    detail = resp.json().get('detail')
    if not isinstance(detail, list):
        return
    for item in detail:
        if isinstance(item, dict):
            assert item.get('loc') != ['query', 'auth_token']


def test_staging_delete_without_query_token_is_not_422(monkeypatch):
    """缺 query auth_token 时不再 422；无登录头则 401。"""
    resp = _delete(_client(monkeypatch))
    assert resp.status_code == 401
    assert resp.json()['error_code'] == 'missing_auth_token'
    _assert_not_query_token_422(resp)


def test_staging_delete_header_auth_reaches_handler(monkeypatch):
    """Authorization 头（含裸 token）通过校验后，不存在的文件返回 404 而不是 422。"""
    monkeypatch.setattr(script_writer, 'FileManager', _FakeFileManager)
    monkeypatch.setattr(script_writer.os.path, 'exists', lambda _path: False)
    client = _client(monkeypatch)
    for authorization in ('Bearer valid-token', 'valid-token'):
        resp = _delete(client, headers={'Authorization': authorization})
        assert resp.status_code == 404, authorization
        body = resp.json()
        assert body['success'] is False
        assert body['error'] == '文件不存在'
        _assert_not_query_token_422(resp)


def test_staging_delete_character_location_prop_same_auth(monkeypatch):
    """角色卡、场景、道具与剧本走同一个删除接口，同样不要求 query auth_token。"""
    monkeypatch.setattr(script_writer, 'FileManager', _FakeFileManager)
    monkeypatch.setattr(script_writer.os.path, 'exists', lambda _path: False)
    client = _client(monkeypatch)
    cases = (
        ('characters', 'hero.json'),
        ('locations', 'room.json'),
        ('props', 'sword.json'),
        ('scripts', '1.json'),
    )
    for folder, filename in cases:
        resp = _delete(
            client,
            headers={'Authorization': 'valid-token'},
            folder=folder,
            filename=filename,
        )
        assert resp.status_code == 404, folder
        assert resp.json()['error'] == '文件不存在'
        _assert_not_query_token_422(resp)


def test_staging_delete_user_mismatch_rejected(monkeypatch):
    resp = _delete(
        _client(monkeypatch, token_user_id=7),
        headers={'Authorization': 'Bearer valid-token'},
        user_id='2',
    )
    assert resp.status_code == 403
    assert resp.json()['error_code'] == 'user_mismatch'


def test_staging_delete_invalid_token_rejected(monkeypatch):
    resp = _delete(
        _client(monkeypatch),
        headers={'Authorization': 'Bearer wrong-token'},
    )
    assert resp.status_code == 401
    assert resp.json()['error_code'] == 'invalid_auth_token'
