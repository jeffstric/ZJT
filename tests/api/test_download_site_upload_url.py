"""本站域名 /upload/ 媒体 URL 的下载：改写为 CDN 域名后走签名重定向。

火山 TTS 等本地落盘产物返回 {server.host}/upload/... 完整 URL，浏览器播放时
cdn_redirect_middleware 302 到七牛（媒体流量不过本服务）。/api/download 收到
同款 URL 时也必须走 CDN 签名重定向，而不是落入代理下载分支——否则服务器要
从 CDN 拉回整个文件再吐给浏览器（白占 frp 隧道带宽），且 httpx 不跟随 302
直接报错（TTS 音频下载 302 事故）。
"""
import pytest
from fastapi.testclient import TestClient

from model.media_file_mapping import MediaFileMappingModel

SIGNED = "https://cdntest.perseids.cn/upload/tts/volcengine/a.mp3?e=1&token=sig&attname=a.mp3"
TTS_URL = "http://zjt-dev.perseids.cn/upload/tts/volcengine/a.mp3"


@pytest.fixture
def client(monkeypatch):
    import server

    monkeypatch.setattr(
        "model.user_tokens.UserTokensModel.get_user_id_by_token",
        staticmethod(lambda token: 1 if token == "valid-token" else None),
    )
    return TestClient(server.app)


@pytest.fixture
def site_env(monkeypatch):
    """server.host 指向 zjt-dev，qiniu_long_term CDN 域名为 cdntest。"""
    import server

    monkeypatch.setattr(server, "get_config", lambda: {"server": {"host": "http://zjt-dev.perseids.cn"}})

    def _fake_dynamic(*keys, **kwargs):
        if keys == ("file_storage", "qiniu_long_term", "cdn_domain"):
            return "cdntest.perseids.cn"
        return kwargs.get("default", "")

    monkeypatch.setattr(server, "get_dynamic_config_value", _fake_dynamic)


def _patch_cdn(monkeypatch, is_cdn=True, signed=SIGNED):
    import utils.cdn_util as cdn_mod

    monkeypatch.setattr(cdn_mod.CDNUtil, "is_cdn_url", staticmethod(lambda url: is_cdn))
    monkeypatch.setattr(
        cdn_mod.CDNUtil,
        "get_signed_download_url",
        staticmethod(lambda url, attname: signed if signed else None),
    )


def _patch_mapping(monkeypatch, cloud_path="upload/tts/volcengine/a.mp3"):
    """cloud_path=None 模拟未注册映射/未上传完成。"""
    import types

    mapping = types.SimpleNamespace(cloud_path=cloud_path) if cloud_path else None
    monkeypatch.setattr(
        MediaFileMappingModel,
        "get_by_local_path_hash",
        staticmethod(lambda url_hash: mapping),
    )


def _patch_proxy_client(monkeypatch, content=b"mp3-bytes", content_type="audio/mpeg"):
    class _FakeResp:
        def __init__(self):
            self.headers = {"content-type": content_type}
            self.content = content

        def raise_for_status(self):
            pass

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return _FakeResp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)


def test_site_upload_url_with_cdn_mapping_returns_signed_json(client, monkeypatch, site_env):
    """已注册 CDN 映射的本站 /upload/ URL：改写为 CDN 域名后走重签名，format=json
    返回 redirect_url，媒体流量不过本服务。http 协议同样命中（协议无关）。"""
    _patch_cdn(monkeypatch)
    _patch_mapping(monkeypatch)
    resp = client.get(
        "/api/download",
        params={"url": TTS_URL, "filename": "audio.mp3", "format": "json"},
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["redirect_url"] == SIGNED


def test_rewrite_uses_cdn_domain_and_mapped_cloud_path(client, monkeypatch, site_env):
    """改写目标 = qiniu_long_term CDN 域名 + 映射表 cloud_path（key 可能与本地路径不同）。"""
    seen = {}

    import utils.cdn_util as cdn_mod

    def _fake_is_cdn(url):
        seen["is_cdn"] = url
        return True

    def _fake_signed(url, attname):
        seen["signed"] = url
        return SIGNED

    monkeypatch.setattr(cdn_mod.CDNUtil, "is_cdn_url", staticmethod(_fake_is_cdn))
    monkeypatch.setattr(cdn_mod.CDNUtil, "get_signed_download_url", staticmethod(_fake_signed))
    _patch_mapping(monkeypatch, cloud_path="upload/tts/volcengine/renamed-key.mp3")

    resp = client.get(
        "/api/download",
        params={"url": TTS_URL, "filename": "audio.mp3"},
        headers={"Authorization": "Bearer valid-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == SIGNED
    assert seen["is_cdn"] == "https://cdntest.perseids.cn/upload/tts/volcengine/renamed-key.mp3"
    assert seen["signed"] == seen["is_cdn"]


def test_site_upload_url_without_mapping_falls_back_to_proxy(client, monkeypatch, site_env):
    """无 CDN 映射（未注册/上传未完成）：不改写，落代理下载兜底，仍能下载。"""
    _patch_cdn(monkeypatch, is_cdn=False)
    _patch_mapping(monkeypatch, cloud_path=None)
    _patch_proxy_client(monkeypatch)

    resp = client.get(
        "/api/download",
        params={"url": TTS_URL, "filename": "audio.mp3", "format": "json"},
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/mpeg")
    assert resp.content == b"mp3-bytes"


def test_foreign_host_upload_url_never_queries_mapping(client, monkeypatch, site_env):
    """非本站域名的 /upload/ URL：与本服务无关，不查映射、不改写，走外链代理。"""
    _patch_cdn(monkeypatch, is_cdn=False)
    _patch_proxy_client(monkeypatch)

    def _boom(url_hash):
        raise AssertionError("foreign host URL must not query media_file_mapping")

    monkeypatch.setattr(MediaFileMappingModel, "get_by_local_path_hash", staticmethod(_boom))

    resp = client.get(
        "/api/download",
        params={
            "url": "https://other.example.com/upload/tts/volcengine/a.mp3",
            "filename": "audio.mp3",
        },
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 200
    assert resp.content == b"mp3-bytes"


def test_relative_upload_cache_path_still_local(client, monkeypatch):
    """回归：相对路径 /upload/cache/ 仍走本地 FileResponse 分支，不查映射。"""
    import os

    import server

    def _boom(url_hash):
        raise AssertionError("relative /upload/cache/ path must not query media_file_mapping")

    monkeypatch.setattr(MediaFileMappingModel, "get_by_local_path_hash", staticmethod(_boom))

    cache_dir = os.path.join(os.path.dirname(os.path.abspath(server.__file__)), "upload", "cache")
    os.makedirs(cache_dir, exist_ok=True)
    tmp = os.path.join(cache_dir, "_test_dl_local_mp3.mp3")
    with open(tmp, "wb") as f:
        f.write(b"local-bytes")
    try:
        resp = client.get(
            "/api/download",
            params={"url": "/upload/cache/_test_dl_local_mp3.mp3", "filename": "a.mp3"},
            headers={"Authorization": "Bearer valid-token"},
        )
        assert resp.status_code == 200
        assert resp.content == b"local-bytes"
    finally:
        os.remove(tmp)
