"""故事板导出下载：format=json 用 Authorization 头取 CDN 重签名地址。

<a href> 跳转带不上头，只能靠 cookie。cookie 失效而 localStorage token 仍有效时，
必须能靠 Bearer 头拿到 redirect_url，且请求 URL 不含登录 token。
"""
import pytest
from fastapi.testclient import TestClient


SIGNED = "https://cdn.example.com/export/clip.mp4?e=1&token=cdn-sig&attname=clip.mp4"


@pytest.fixture
def client(monkeypatch):
    import server

    monkeypatch.setattr(
        "model.user_tokens.UserTokensModel.get_user_id_by_token",
        staticmethod(lambda token: 1 if token == "valid-token" else None),
    )
    return TestClient(server.app)


def _patch_cdn(monkeypatch, is_cdn=True, signed=SIGNED):
    import utils.cdn_util as cdn_mod

    monkeypatch.setattr(cdn_mod.CDNUtil, "is_cdn_url", staticmethod(lambda url: is_cdn))
    monkeypatch.setattr(
        cdn_mod.CDNUtil,
        "get_signed_download_url",
        staticmethod(lambda url, attname: signed if signed else None),
    )


def test_format_json_accepts_bearer_even_if_cookie_is_stale(client, monkeypatch):
    _patch_cdn(monkeypatch)
    resp = client.get(
        "/api/download",
        params={
            "url": "https://cdn.example.com/export/clip.mp4?e=1&token=old",
            "filename": "clip.mp4",
            "format": "json",
        },
        headers={"Authorization": "Bearer valid-token"},
        cookies={"auth_token": "expired-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["redirect_url"] == SIGNED
    assert "auth_token=" not in str(resp.request.url)
    assert "valid-token" not in str(resp.request.url)
    assert "valid-token" not in body["redirect_url"]


def test_format_json_cookie_only_stale_token_is_401(client, monkeypatch):
    _patch_cdn(monkeypatch)
    resp = client.get(
        "/api/download",
        params={
            "url": "https://cdn.example.com/export/clip.mp4",
            "filename": "clip.mp4",
            "format": "json",
        },
        cookies={"auth_token": "expired-token"},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "invalid_auth_token"


def test_default_cdn_download_still_redirects(client, monkeypatch):
    _patch_cdn(monkeypatch)
    resp = client.get(
        "/api/download",
        params={
            "url": "https://cdn.example.com/export/clip.mp4",
            "filename": "clip.mp4",
        },
        headers={"Authorization": "Bearer valid-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == SIGNED


def test_format_json_non_cdn_falls_back_to_proxy_stream(client, monkeypatch):
    """非 CDN 外链 + format=json：无法签名时降级代理流式下载（200 + 文件流），
    不再 400。前端 downloadWithAuth 对非 JSON 响应走 blob 兜底。"""
    _patch_cdn(monkeypatch, is_cdn=False)
    _patch_safe_proxy_fetch(monkeypatch, content=b"png-bytes", content_type="image/png")
    resp = client.get(
        "/api/download",
        params={
            "url": "https://example.com/not-cdn.png",
            "filename": "pic.png",
            "format": "json",
        },
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
    assert resp.content == b"png-bytes"


def _patch_safe_proxy_fetch(monkeypatch, content=b"mp3-bytes", content_type="audio/mpeg"):
    """模拟 _safe_proxy_fetch 的 httpx.stream 调用形态并跳过 DNS 目标校验。

    SSRF 目标校验（_assert_proxy_fetch_target）由
    tests/api/test_openvuln_cvss8_infra_guards.py 独立覆盖，本文件只关心
    代理回退行为本身。
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
