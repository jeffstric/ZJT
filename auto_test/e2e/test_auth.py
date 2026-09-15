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
    def test_logout_success(self, base_url, e2e_config):
        """使用次账号验证登出，避免注销后续用例共用的主账号 token。

        必须在本用例内新登录拿 fresh token：单会话策略下，前面
        test_login_success 的次账号登录已把 session 级 secondary_auth_token
        顶掉（delete_by_user_id），直接用它登出会 401。
        本用例位于 auth 模块，之后无用例再依赖旧的次账号 token。
        """
        creds = e2e_config["credentials"]["secondary"]
        try:
            login_resp = httpx.post(
                f"{base_url}/api/auth/login",
                json={"phone": creds["phone"], "password": creds["password"]},
                timeout=10,
            )
            assert login_resp.status_code == 200
            login_data = login_resp.json()
            token = (login_data.get("data") or login_data).get("token")
            user_id = (login_data.get("data") or login_data).get("user_id")
            assert token, f"登录响应中未找到 token: {login_data}"
            # 防 user_id 缺失时发出 X-User-Id: "None"
            assert user_id, f"登录响应中未找到 user_id: {login_data}"
            resp = httpx.post(
                f"{base_url}/api/auth/logout",
                json={"auth_token": token},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-User-Id": str(user_id),
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
