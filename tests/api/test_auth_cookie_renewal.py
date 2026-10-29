"""认证 cookie 滑动续期判定（decide_auth_cookie_renewal）单元测试。

覆盖 utils.resource_access.decide_auth_cookie_renewal——
auth_cookie_translation_middleware 响应阶段的续期判定核心：

- 非 /api/ 路径、无 cookie → 不续
- /api/auth/ 前缀（登录/登出/注册自管理 cookie）→ 不续
- 无 Authorization 头（cookie 翻译鉴权路径）→ 续（既有行为）
- Bearer 与 cookie token 相同（单会话正常页面）→ 续（本次修复点）
- Bearer 与 cookie token 不同（多标签页/顶号各持不同 token）→ 不续，
  防止旧 token 覆盖浏览器里较新的 cookie

背景（2026-10-21）：此前 cookie 只在"无 Authorization 头"的请求上续期，页面日常
心跳/SSE 全带 Bearer → DB token 滑动续期而 cookie 不续；cookie 先于 DB token
死亡后，无显式凭证的轮询（get-status）401 → 401 自愈误清仍有效的 localStorage
token → 活跃用户被"假过期"踢到登录页。

不连库：纯函数，直接调用。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def decide(monkeypatch):
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
    from utils.resource_access import decide_auth_cookie_renewal

    return decide_auth_cookie_renewal


class TestNoRenewal:
    def test_non_api_path(self, decide):
        assert decide("/web/marketing_agent.html", None, "tok") is None

    def test_no_cookie(self, decide):
        assert decide("/api/get-status/1", "tok", None) is None
        assert decide("/api/get-status/1", None, None) is None

    def test_auth_prefix_paths_excluded(self, decide):
        """登录/登出/注册端点自管理 cookie，绝不用旧值覆盖响应的 Set-Cookie"""
        assert decide("/api/auth/login", None, "old-tok") is None
        assert decide("/api/auth/login", "old-tok", "old-tok") is None
        assert decide("/api/auth/logout", "tok", "tok") is None
        assert decide("/api/auth/register", "tok", "tok") is None

    def test_bearer_differs_from_cookie(self, decide):
        """多标签页/顶号后各持不同 token：不用旧 Bearer 覆盖较新的 cookie"""
        assert decide("/api/session/1/task", "new-tok", "old-tok") is None
        assert decide("/api/get-status/1,2", "new-tok", "old-tok") is None


class TestRenewal:
    def test_translated_path_no_bearer(self, decide):
        """无 Authorization 头、靠 cookie 翻译鉴权 → 续（既有行为）"""
        assert decide("/api/get-status/1", None, "tok") == "tok"

    def test_bearer_equals_cookie(self, decide):
        """单会话正常页面：Bearer 与 cookie 同源 → 续（修复点）"""
        assert decide("/api/session/create", "tok", "tok") == "tok"
        assert decide("/api/user/role", "tok", "tok") == "tok"
        assert decide("/api", "tok", "tok") == "tok"

    def test_bearer_equals_cookie_heart_beat_endpoints(self, decide):
        """心跳类端点（带 Bearer、与 cookie 同源）同样续期"""
        assert decide("/api/user/computing_power", "tok", "tok") == "tok"
        assert decide("/api/task/9/stream", "tok", "tok") == "tok"
