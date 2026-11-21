"""安全审计 BUG-R2-S1-A2-H2 / A2-H4 / A5-H1 / A9-H4：基础设施防护测试。

- GuardedFilesStatic：/files 匿名静态挂载不得暴露 script_writer/ 与 tmp/ 子树。
- _assert_proxy_fetch_target：代理抓取拒绝环回/私网/链路本地（云元数据）目标。
- /api/test/ask-user：调试路由必须已从生产 app 卸载。
- media._resolve_url_to_local_path：/upload/ URL 解析拒绝路径穿越（ffprobe 探测面）。
- media.validate-duration：未登录拒绝；上传走安全漏斗失败时清理临时文件。
"""
import io
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile


# ==================== A2-H2：GuardedFilesStatic ====================

@pytest.fixture
def files_client(tmp_path):
    import server

    (tmp_path / 'script_writer' / '1' / '1').mkdir(parents=True)
    (tmp_path / 'script_writer' / '1' / '1' / 'character_x.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'tmp').mkdir()
    (tmp_path / 'tmp' / 'secret.wav').write_bytes(b'x')
    (tmp_path / 'logo.svg').write_text('<svg/>', encoding='utf-8')

    app = FastAPI()
    app.mount('/files', server.GuardedFilesStatic(directory=str(tmp_path)), name='files')
    return TestClient(app)


@pytest.mark.parametrize('path', [
    '/files/script_writer/1/1/character_x.json',
    '/files/tmp/secret.wav',
    '/files/./script_writer/1/1/character_x.json',
    '/files/script_writer%2f1%2f1%2fcharacter_x.json',
])
def test_files_static_blocks_user_data_trees(files_client, path):
    resp = files_client.get(path)
    assert resp.status_code == 404


def test_files_static_still_serves_brand_assets(files_client):
    resp = files_client.get('/files/logo.svg')
    assert resp.status_code == 200


# ==================== A5-H1：代理抓取 SSRF 收口 ====================

@pytest.mark.parametrize('url', [
    'http://127.0.0.1/',
    'http://127.0.0.1:9003/api/auth/me',
    'http://169.254.169.254/latest/meta-data/',   # AWS/阿里云元数据
    'http://100.100.100.200/latest/meta-data/',
    'http://10.1.2.3/',
    'http://192.168.1.1/',
    'http://172.16.0.1/',
    'http://0.0.0.0/',
    'http://[::1]/',
    'http://[fd00::1]/',                          # IPv6 ULA
    'http://[::ffff:127.0.0.1]/',                 # IPv4-mapped IPv6
    'file:///etc/passwd',
    'ftp://example.com/x',
    'gopher://127.0.0.1:6379/_INFO',
])
def test_assert_proxy_fetch_target_rejects_unfetchable(url):
    import asyncio

    import server
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(server._assert_proxy_fetch_target(url))
    assert exc_info.value.status_code == 400


def test_safe_proxy_fetch_rejects_before_any_request():
    """内网目标在发起任何 HTTP 请求前即被拒绝"""
    import asyncio

    import server
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(server._safe_proxy_fetch('http://127.0.0.1:9003/x', timeout=5.0))
    assert exc_info.value.status_code == 400


# ==================== A9-H4：test/ask-user 调试路由已卸载 ====================

def test_test_ask_user_router_unmounted():
    import server

    paths = {getattr(route, 'path', '') for route in server.app.routes}
    assert '/api/test/ask-user' not in paths
    assert not any(p.startswith('/api/test') for p in paths)


# ==================== A2-H4：media validate-duration ====================

def test_resolve_url_to_local_path_rejects_traversal(tmp_path, monkeypatch):
    from api import media

    monkeypatch.setattr(media, 'PROJECT_ROOT', str(tmp_path))
    upload_dir = tmp_path / 'upload' / 'cache'
    upload_dir.mkdir(parents=True)
    (upload_dir / 'ok.mp3').write_bytes(b'x')

    assert media._resolve_url_to_local_path('/upload/cache/ok.mp3') is not None
    # 穿越出 upload 目录（ffprobe 存在性探测面）
    assert media._resolve_url_to_local_path('/upload/../../etc/passwd') is None
    assert media._resolve_url_to_local_path('/upload/cache/../../../config_dev.yml') is None
    assert media._resolve_url_to_local_path('/upload/cache/./a.mp3') is None
    assert media._resolve_url_to_local_path('/upload/cache/..%2F..%2Fx') is None
    # Windows 反斜杠变体
    assert media._resolve_url_to_local_path('/upload/cache/..\\..\\x') is None
    # 绝对盘符段（os.path.join 遇绝对段会丢弃 upload_dir）
    assert media._resolve_url_to_local_path('/upload/cache/C:/evil.mp3') is None


def test_validate_duration_requires_login(tmp_path, monkeypatch):
    from api import media

    _token_stub(monkeypatch)
    app = FastAPI()
    app.post('/api/media/validate-duration')(media.validate_media_duration)
    client = TestClient(app)
    resp = client.post('/api/media/validate-duration')
    assert resp.status_code == 401


def test_validate_duration_rejects_too_many_files(tmp_path, monkeypatch):
    from api import media

    _token_stub(monkeypatch)
    app = FastAPI()
    app.post('/api/media/validate-duration')(media.validate_media_duration)
    client = TestClient(app)
    limit = media.MediaConstants.VALIDATE_DURATION_MAX_FILES
    files = [('audio_files', (f'a{i}.mp3', b'\xfffb', 'audio/mpeg')) for i in range(limit + 1)]
    resp = client.post(
        '/api/media/validate-duration', headers=_auth(), files=files,
    )
    assert resp.status_code == 400
    assert '最多' in resp.json()['detail']


def test_save_upload_files_cleans_temp_on_validation_failure(tmp_path, monkeypatch):
    """魔数校验失败（伪造扩展名）→ UploadValidationError 且无临时文件泄漏"""
    from api import media

    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    fake = UploadFile(file=io.BytesIO(b'not-an-mp3-at-all'), filename='evil.mp3')

    import asyncio

    with pytest.raises(media.UploadValidationError):
        asyncio.run(media._save_upload_files([fake]))

    leftovers = [p for p in tmp_path.iterdir() if p.is_file()]
    assert leftovers == []


def _auth():
    return {'Authorization': 'Bearer valid-token'}


def _token_stub(monkeypatch):
    from model.user_tokens import UserTokensModel

    monkeypatch.setattr(
        UserTokensModel,
        'get_user_id_by_token',
        staticmethod(lambda token: 7 if token == 'valid-token' else None),
    )
