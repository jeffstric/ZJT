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


def test_format_json_non_cdn_does_not_proxy_body(client, monkeypatch):
    _patch_cdn(monkeypatch, is_cdn=False)
    resp = client.get(
        "/api/download",
        params={
            "url": "https://example.com/not-cdn.mp4",
            "filename": "clip.mp4",
            "format": "json",
        },
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 400
    assert resp.json()["success"] is False
