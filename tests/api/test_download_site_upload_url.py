"""本站域名 /upload/ 媒体 URL 的下载：改写为 CDN 域名后走签名重定向。

火山 TTS 等本地落盘产物返回 {server.host}/upload/... 完整 URL，浏览器播放时
cdn_redirect_middleware 302 到七牛（媒体流量不过本服务）。/api/download 收到
同款 URL 时也必须走 CDN 签名重定向，而不是落入代理下载分支——否则服务器要
从 CDN 拉回整个文件再吐给浏览器（白占 frp 隧道带宽），且 httpx 不跟随 302
直接报错（TTS 音频下载 302 事故）。
"""
from urllib.parse import quote

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
    """模拟 _safe_proxy_fetch 的 httpx.stream 调用形态并跳过 DNS 目标校验。

    SSRF 目标校验（_assert_proxy_fetch_target）由
    tests/api/test_openvuln_cvss8_infra_guards.py 独立覆盖。
    """
    import httpx

    async def _noop_assert(url):
        return None

    monkeypatch.setattr("server._assert_proxy_fetch_target", _noop_assert)

    fake_request = httpx.Request("GET", "https://example.com/fake")

    class _FakeStreamResp:
        is_redirect = False
        status_code = 200
        headers = {"content-type": content_type}
        request = fake_request

        async def aiter_bytes(self):
            yield content

    class _FakeStreamCtx:
        async def __aenter__(self):
            return _FakeStreamResp()

        async def __aexit__(self, *exc):
            return False

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url):
            return _FakeStreamCtx()

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


def _forbid_proxy(monkeypatch):
    async def _boom(url, *, timeout):
        raise AssertionError(f"must not proxy {url}")

    monkeypatch.setattr("server._safe_proxy_fetch", _boom)


def _write_upload(rel_parts, content):
    """在项目 upload/ 下写测试文件，返回绝对路径。"""
    import os

    import server

    root = os.path.join(os.path.dirname(os.path.abspath(server.__file__)), "upload", *rel_parts[:-1])
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, rel_parts[-1])
    with open(path, "wb") as f:
        f.write(content)
    return path


def test_localhost_draft_zip_served_locally_not_proxied(client, monkeypatch):
    """本机素材包：downloadWithAuth 会把 /upload/draft/ 补成 http://localhost/...。
    无 CDN 映射时必须直接读本地 zip，不能代理环回地址（否则 400
    「不允许代理内网/环回/保留地址」）。路径里的中文保持百分号编码。"""
    import os

    _patch_mapping(monkeypatch, cloud_path=None)
    _forbid_proxy(monkeypatch)
    payload = b"PK\x03\x04draft-zip"
    name = "剧本拆分测试_素材_test.zip"
    path = _write_upload(("draft", "_download_api_test", name), payload)
    encoded = "http://localhost:13008/upload/draft/_download_api_test/" + quote(name)
    try:
        resp = client.get(
            "/api/download",
            params={"url": encoded, "filename": name, "format": "json"},
            headers={"Authorization": "Bearer valid-token"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.content == payload
        assert resp.headers["content-type"].startswith("application/zip")
        disposition = resp.headers.get("content-disposition", "")
        assert "attachment" in disposition.lower()
    finally:
        os.remove(path)


def test_localhost_timeline_video_served_locally(client, monkeypatch):
    """本机成品视频：导出接口返回 http://localhost/.../timeline_video_export/*.mp4。"""
    import os

    _patch_mapping(monkeypatch, cloud_path=None)
    _forbid_proxy(monkeypatch)
    payload = b"\x00\x00\x00\x18ftypmp42"
    path = _write_upload(("timeline_video_export", "_download_api_test", "timeline_test.mp4"), payload)
    try:
        resp = client.get(
            "/api/download",
            params={
                "url": "http://127.0.0.1:13008/upload/timeline_video_export/_download_api_test/timeline_test.mp4",
                "filename": "timeline_test.mp4",
                "format": "json",
            },
            headers={"Authorization": "Bearer valid-token"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.content == payload
        assert resp.headers["content-type"].startswith("video/mp4")
    finally:
        os.remove(path)


def test_relative_draft_zip_served_locally(client, monkeypatch):
    """相对路径 /upload/draft/ 同样走本地文件，不查 CDN 映射。"""
    import os

    def _boom(url_hash):
        raise AssertionError("relative /upload/draft/ must not query media_file_mapping")

    monkeypatch.setattr(MediaFileMappingModel, "get_by_local_path_hash", staticmethod(_boom))
    _forbid_proxy(monkeypatch)
    payload = b"relative-zip"
    path = _write_upload(("draft", "_download_api_test", "relative.zip"), payload)
    try:
        resp = client.get(
            "/api/download",
            params={"url": "/upload/draft/_download_api_test/relative.zip", "filename": "relative.zip"},
            headers={"Authorization": "Bearer valid-token"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.content == payload
    finally:
        os.remove(path)


def test_localhost_upload_missing_file_is_404_not_ssrf(client, monkeypatch):
    """环回 /upload/ 文件不存在时返回 404，而不是代理后的 400。"""
    _patch_mapping(monkeypatch, cloud_path=None)
    _forbid_proxy(monkeypatch)
    resp = client.get(
        "/api/download",
        params={
            "url": "http://localhost:13008/upload/draft/_download_api_test/missing.zip",
            "filename": "missing.zip",
            "format": "json",
        },
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "本地文件不存在"


def test_localhost_upload_traversal_rejected(client, monkeypatch):
    """环回地址也不能用 ../ 读出 upload 目录之外的文件。"""
    _forbid_proxy(monkeypatch)
    resp = client.get(
        "/api/download",
        params={"url": "http://127.0.0.1:13008/upload/../server.py", "filename": "server.py"},
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "本地路径非法"
    assert b"FastAPI" not in resp.content


def test_localhost_upload_with_cdn_mapping_still_uses_cdn(client, monkeypatch, site_env):
    """已有 CDN 映射时，即使本机也有同名文件，仍然走签名地址，不读本地字节。"""
    import os

    import server

    monkeypatch.setattr(server, "get_config", lambda: {"server": {"host": "http://localhost:13008"}})
    _patch_cdn(monkeypatch)
    _patch_mapping(monkeypatch, cloud_path="upload/draft/_download_api_test/mapped.zip")
    _forbid_proxy(monkeypatch)
    payload = b"local-should-not-leak"
    path = _write_upload(("draft", "_download_api_test", "mapped.zip"), payload)
    try:
        resp = client.get(
            "/api/download",
            params={
                "url": "http://localhost:13008/upload/draft/_download_api_test/mapped.zip",
                "filename": "mapped.zip",
                "format": "json",
            },
            headers={"Authorization": "Bearer valid-token"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["redirect_url"] == SIGNED
        assert resp.content != payload
    finally:
        os.remove(path)


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
