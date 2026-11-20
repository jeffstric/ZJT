"""认证 cookie 名端口隔离（get_auth_cookie_name）单元测试。

背景：同一浏览器里 localhost:13003 / localhost:13004 等多个本机环境共享
cookie 作用域（浏览器 cookie 只按 host 匹配、不区分端口），同名 auth_token
互相覆盖，后登录的环境会顶掉先登录环境的会话（各环境数据库独立、token
互不识别 → 401 假过期）。修复后带显式非默认端口访问时 cookie 名追加端口
后缀（auth_token_13003），各端口环境互不可见；无端口 / 默认端口（80/443
反代形态）保持基础名 auth_token，线上存量会话不受影响。

覆盖：
- utils.resource_access.get_auth_cookie_name（host 形态矩阵）
- server.set_auth_cookie（Set-Cookie 名带端口后缀）
- utils.resource_access.enforce_x_user_id_consistency（cookie 兜底读取用动态名）
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _seed_config_cache(monkeypatch):
    monkeypatch.setenv("comfyui_env", "unit")
    import config.config_util as config_util

    config_util._config_cache["config_unit.yml"] = {
        "database": {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "unit",
            "password": "unit",
            "database": "unit",
        }
    }


@pytest.fixture
def resource_access(monkeypatch):
    _seed_config_cache(monkeypatch)
    import utils.resource_access as ra

    # token → user_id 映射：t11→11，其余 → None（无效/过期）
    monkeypatch.setattr(
        "model.user_tokens.UserTokensModel.get_user_id_by_token",
        staticmethod(lambda token: {"t11": 11}.get(token)),
    )
    return ra


def _request(path="/api/worlds", host="localhost:13003", headers=None, cookies=None):
    raw_headers = [(b"host", str(host).encode())]
    for k, v in (headers or {}).items():
        raw_headers.append((k.lower().encode(), str(v).encode()))
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers.append((b"cookie", cookie_str.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
        "scheme": "http",
    }
    return Request(scope)


def _first_cookie_pair(set_cookie_header: str) -> str:
    return set_cookie_header.split(";")[0].strip()


# ---------------- get_auth_cookie_name ----------------

class TestGetAuthCookieName:
    def test_explicit_dev_port_suffixed(self, resource_access):
        req = _request(host="localhost:13003")
        assert resource_access.get_auth_cookie_name(req) == "auth_token_13003"

    def test_different_ports_get_different_names(self, resource_access):
        """同浏览器多端口环境互不覆盖的关键性质"""
        n1 = resource_access.get_auth_cookie_name(_request(host="localhost:13003"))
        n2 = resource_access.get_auth_cookie_name(_request(host="localhost:13004"))
        assert n1 != n2

    def test_no_port_keeps_base_name(self, resource_access):
        """反代形态（Host 无端口）：保持基础名，线上存量会话不受影响"""
        req = _request(host="localhost")
        assert resource_access.get_auth_cookie_name(req) == "auth_token"

    def test_default_http_port_normalized(self, resource_access):
        """显式 80 与不带端口视为同一形态，避免同服务产生两套 cookie 名"""
        req = _request(host="localhost:80")
        assert resource_access.get_auth_cookie_name(req) == "auth_token"

    def test_default_https_port_normalized(self, resource_access):
        req = _request(host="example.com:443")
        assert resource_access.get_auth_cookie_name(req) == "auth_token"

    def test_ipv6_port_suffixed(self, resource_access):
        req = _request(host="[::1]:13005")
        assert resource_access.get_auth_cookie_name(req) == "auth_token_13005"


# ---------------- set_auth_cookie（server 侧写入） ----------------

class TestSetAuthCookie:
    def test_set_cookie_uses_port_suffixed_name(self):
        import server

        resp = JSONResponse(content={"ok": True})
        server.set_auth_cookie(resp, "tok-1", _request(host="localhost:13003"))
        set_cookies = [
            _first_cookie_pair(c) for c in resp.headers.getlist("set-cookie")
        ]
        assert "auth_token_13003=tok-1" in set_cookies

    def test_set_cookie_no_port_uses_base_name(self):
        import server

        resp = JSONResponse(content={"ok": True})
        server.set_auth_cookie(resp, "tok-2", _request(host="localhost"))
        set_cookies = [
            _first_cookie_pair(c) for c in resp.headers.getlist("set-cookie")
        ]
        assert "auth_token=tok-2" in set_cookies


# ---------------- X-User-Id 一致性兜底读取 ----------------

class TestXUserIdCookieFallback:
    def test_port_suffixed_cookie_accepted(self, resource_access):
        req = _request(
            host="localhost:13003",
            headers={"X-User-Id": "11"},
            cookies={"auth_token_13003": "t11"},
        )
        assert asyncio.run(resource_access.enforce_x_user_id_consistency(req)) is None

    def test_base_name_cookie_ignored_when_port_present(self, resource_access):
        """带端口访问只认带后缀名：旧基础名 cookie 不再兜底（避免串环境）"""
        req = _request(
            host="localhost:13003",
            headers={"X-User-Id": "11"},
            cookies={"auth_token": "t11"},
        )
        resp = asyncio.run(resource_access.enforce_x_user_id_consistency(req))
        assert resp is not None and resp.status_code == 401
