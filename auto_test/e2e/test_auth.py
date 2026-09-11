"""认证模块 E2E 测试"""
import httpx
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.auth, pytest.mark.ci_smoke]

class TestAuth:
    """认证模块测试"""

    @pytest.mark.p0
    def test_login_success(self, base_url, e2e_config):
        """正确手机号+密码登录成功，返回 token 和 user_id。

        必须用次账号：登录接口是单会话策略，主账号任何一次新登录都会删除
        主账号全部旧 token（auth_service.py delete_by_user_id），会顶掉
        session 级 auth_token fixture，使后续所有用例 401/400 连环失败。
        与 test_logout_success 同理（避免破坏后续用例共用的凭证）。
        """
        creds = e2e_config["credentials"]["secondary"]
        try:
            resp = httpx.post(
                f"{base_url}/api/auth/login",
                json={"phone": creds["phone"], "password": creds["password"]},
                timeout=10,
            )
        except (httpx.ConnectError, httpx.ReadError) as e:
            pytest.skip(f"服务器不可用: {e}")
        assert resp.status_code == 200
        data = resp.json()
        token = data.get("token") or data.get("access_token") or data.get("data", {}).get("token")
        assert token, f"登录响应中未找到 token: {data}"

    @pytest.mark.p0
    def test_login_wrong_password(self, base_url, e2e_config):
        """错误密码登录失败，返回 400 或非200"""
        creds = e2e_config["credentials"]["primary"]
        try:
            resp = httpx.post(
                f"{base_url}/api/auth/login",
                json={"phone": creds["phone"], "password": "wrong_password_123"},
                timeout=10,
            )
        except (httpx.ConnectError, httpx.ReadError) as e:
            pytest.skip(f"服务器不可用: {e}")
        assert resp.status_code != 200, "错误密码登录应返回非200状态码"

    @pytest.mark.p0
    def test_logout_success(self, base_url, secondary_auth_token, secondary_user_id):
        """使用次账号验证登出，避免注销后续用例共用的主账号 token。"""
        try:
            resp = httpx.post(
                f"{base_url}/api/auth/logout",
                json={"auth_token": secondary_auth_token},
                headers={
                    "Authorization": f"Bearer {secondary_auth_token}",
                    "X-User-Id": str(secondary_user_id),
                },
                timeout=10,
            )
        except (httpx.ConnectError, httpx.ReadError) as e:
            pytest.skip(f"服务器不可用: {e}")
        assert resp.status_code == 200

    # ────────────────── P1 测试 ──────────────────

    @pytest.mark.p1
    def test_login_empty_phone(self, base_url, e2e_config):
        """P1: 空手机号登录应返回非200"""
        creds = e2e_config["credentials"]["primary"]
        try:
            resp = httpx.post(
                f"{base_url}/api/auth/login",
                json={"phone": "", "password": creds["password"]},
                timeout=10,
            )
        except (httpx.ConnectError, httpx.ReadError) as e:
            pytest.skip(f"服务器不可用: {e}")
        assert resp.status_code != 200, "空手机号登录应返回非200状态码"

    @pytest.mark.p1
    def test_login_empty_password(self, base_url, e2e_config):
        """P1: 空密码登录应返回非200"""
        creds = e2e_config["credentials"]["primary"]
        try:
            resp = httpx.post(
                f"{base_url}/api/auth/login",
                json={"phone": creds["phone"], "password": ""},
                timeout=10,
            )
        except (httpx.ConnectError, httpx.ReadError) as e:
            pytest.skip(f"服务器不可用: {e}")
        assert resp.status_code != 200, "空密码登录应返回非200状态码"

    @pytest.mark.p1
    def test_login_nonexistent_user(self, base_url):
        """P1: 不存在的用户登录应返回非200"""
        import random
        fake_phone = f"1{random.randint(30, 99):02d}{random.randint(10000000, 99999999)}"
        try:
            resp = httpx.post(
                f"{base_url}/api/auth/login",
                json={"phone": fake_phone, "password": "any_password"},
                timeout=10,
            )
        except (httpx.ConnectError, httpx.ReadError) as e:
            pytest.skip(f"服务器不可用: {e}")
        assert resp.status_code != 200, "不存在的用户登录应返回非200状态码"
