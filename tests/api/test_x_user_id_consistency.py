"""X-User-Id 防冒充（"伪主人"漏洞修复）单元测试。

覆盖：
- utils.resource_access.resolve_authenticated_user_id（/api/worlds* 系列端点的身份来源）
- utils.resource_access.enforce_x_user_id_consistency（全站 X-User-Id 一致性中间件核心）

验证矩阵（与修复方案一致）：
- 无 token + X-User-Id: 11            → 401
- user 35 的 token + X-User-Id: 11    → 401（属主不匹配 user_mismatch）
- token 与 X-User-Id 一致             → 放行 / 返回真实 user_id
- cookie 会话（无 Authorization 头）   → 走 AUTH_COOKIE_NAME 兜底，照常校验

不连库：UserTokensModel.get_user_id_by_token 全部 monkeypatch。
"""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
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

    # token → user_id 映射：t11→11, t35→35，其余 → None（无效/过期）
    monkeypatch.setattr(
        "model.user_tokens.UserTokensModel.get_user_id_by_token",
        staticmethod(lambda token: {"t11": 11, "t35": 35}.get(token)),
    )
    return ra


def _request(path="/api/worlds", headers=None, cookies=None):
    raw_headers = [(k.lower().encode(), str(v).encode()) for k, v in (headers or {}).items()]
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers.append((b"cookie", cookie_str.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
    }
    return Request(scope)


# ---------------- resolve_authenticated_user_id ----------------

class TestResolveAuthenticatedUserId:
    def test_missing_token_401(self, resource_access):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(resource_access.resolve_authenticated_user_id(None, 11))
        assert exc.value.status_code == 401

    def test_invalid_token_401(self, resource_access):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(resource_access.resolve_authenticated_user_id("Bearer bad-token", 11))
        assert exc.value.status_code == 401

    def test_mismatched_claimed_user_401(self, resource_access):
        """user 35 的 token + 自称 11 → 401"""
        with pytest.raises(HTTPException) as exc:
            asyncio.run(resource_access.resolve_authenticated_user_id("Bearer t35", 11))
        assert exc.value.status_code == 401

    def test_match_returns_token_user(self, resource_access):
        assert asyncio.run(resource_access.resolve_authenticated_user_id("Bearer t11", 11)) == 11

    def test_bare_token_accepted(self, resource_access):
        assert asyncio.run(resource_access.resolve_authenticated_user_id("t11", "11")) == 11

    def test_claimed_absent_uses_token_user(self, resource_access):
        """未自报 user_id 时以 token 属主为准"""
        assert asyncio.run(resource_access.resolve_authenticated_user_id("Bearer t35", None)) == 35


# ---------------- enforce_x_user_id_consistency ----------------

class TestEnforceXUserIdConsistency:
    def test_non_api_path_passes(self, resource_access):
        req = _request(path="/web/index.html", headers={"X-User-Id": "11"})
        assert asyncio.run(resource_access.enforce_x_user_id_consistency(req)) is None

    def test_no_x_user_id_header_passes(self, resource_access):
        req = _request(path="/api/edition")
        assert asyncio.run(resource_access.enforce_x_user_id_consistency(req)) is None

    def test_x_user_id_without_token_401(self, resource_access):
        """无 token + X-User-Id: 11 → 401 missing_auth_token"""
        req = _request(path="/api/worlds/1/hide", headers={"X-User-Id": "11"})
        resp = asyncio.run(resource_access.enforce_x_user_id_consistency(req))
        assert resp.status_code == 401
        assert resp.body and b"missing_auth_token" in resp.body

    def test_invalid_token_401(self, resource_access):
        req = _request(
            path="/api/worlds",
            headers={"X-User-Id": "11", "Authorization": "Bearer bad-token"},
        )
        resp = asyncio.run(resource_access.enforce_x_user_id_consistency(req))
        assert resp.status_code == 401
        assert b"invalid_auth_token" in resp.body

    def test_mismatch_401(self, resource_access):
        """user 35 的 token + X-User-Id: 11 → 401 user_mismatch"""
        req = _request(
            path="/api/worlds/1/hide",
            headers={"X-User-Id": "11", "Authorization": "Bearer t35"},
        )
        resp = asyncio.run(resource_access.enforce_x_user_id_consistency(req))
        assert resp.status_code == 401
        assert b"user_mismatch" in resp.body

    def test_consistent_passes(self, resource_access):
        req = _request(
            path="/api/worlds",
            headers={"X-User-Id": "11", "Authorization": "Bearer t11"},
        )
        assert asyncio.run(resource_access.enforce_x_user_id_consistency(req)) is None

    def test_cookie_fallback_consistent_passes(self, resource_access):
        """无 Authorization 头时回退认证 cookie（与 cookie 翻译中间件顺序无关）"""
        from config.constant import AUTH_COOKIE_NAME

        req = _request(
            path="/api/worlds",
            headers={"X-User-Id": "35"},
            cookies={AUTH_COOKIE_NAME: "t35"},
        )
        assert asyncio.run(resource_access.enforce_x_user_id_consistency(req)) is None

    def test_cookie_fallback_mismatch_401(self, resource_access):
        from config.constant import AUTH_COOKIE_NAME

        req = _request(
            path="/api/worlds",
            headers={"X-User-Id": "11"},
            cookies={AUTH_COOKIE_NAME: "t35"},
        )
        resp = asyncio.run(resource_access.enforce_x_user_id_consistency(req))
        assert resp.status_code == 401
        assert b"user_mismatch" in resp.body
