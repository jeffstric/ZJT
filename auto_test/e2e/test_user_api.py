"""
用户资料 API 测试（2026-09 新增功能：昵称修改，api/user.py PUT /api/user/nickname）。

覆盖：
- 鉴权：未登录/无效 token 401
- 正向：设置昵称生效（/api/user/role 可回读）；空串=清除并重置随机默认昵称
- 校验：超过 NICKNAME_MAX_LEN=30 个字符 400
- 每个用例 best-effort 恢复原昵称，不污染账号展示名
"""
import httpx
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.user,
    pytest.mark.p1,
]


def _current_nickname(api_client) -> str:
    """经 /api/user/role 回读当前昵称（前端顶栏展示同源接口）"""
    resp = api_client.get("/api/user/role")
    assert resp.status_code == 200, f"获取用户角色失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("code") == 0, f"响应异常: {data}"
    return data.get("data", {}).get("nickname") or ""


def test_nickname_requires_login(base_url):
    """user_api_001 - 未登录修改昵称 401"""
    resp = httpx.put(
        f"{base_url}/api/user/nickname",
        json={"nickname": "x"},
        timeout=15,
    )
    assert resp.status_code == 401


def test_nickname_invalid_token(base_url):
    """user_api_002 - 无效 token 修改昵称 401"""
    resp = httpx.put(
        f"{base_url}/api/user/nickname",
        json={"nickname": "x"},
        headers={"Authorization": "Bearer invalid-token-xyz"},
        timeout=15,
    )
    assert resp.status_code == 401


def test_nickname_too_long(api_client):
    """user_api_003 - 超过 30 个字符 400"""
    resp = api_client.put("/api/user/nickname", json={"nickname": "测" * 31})
    assert resp.status_code == 400
    assert "30" in resp.json().get("detail", ""), f"应提示长度上限: {resp.text}"


def test_nickname_roundtrip_and_empty_reset(api_client):
    """user_api_004 - 设置昵称生效可回读；空串重置随机默认（非空）；结束后恢复原值"""
    original = _current_nickname(api_client)
    new = "E2E测试昵称_1010"
    try:
        resp = api_client.put("/api/user/nickname", json={"nickname": new})
        assert resp.status_code == 200, f"设置昵称失败: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data.get("code") == 0, f"响应异常: {data}"
        assert data["data"]["nickname"] == new
        assert data["data"]["display_name"] == new
        assert _current_nickname(api_client) == new, "/api/user/role 应回读到新昵称"

        # 空串=清除并重新分配随机趣味默认昵称
        resp = api_client.put("/api/user/nickname", json={"nickname": ""})
        assert resp.status_code == 200, f"重置昵称失败: {resp.status_code} {resp.text}"
        reset = resp.json()["data"]["nickname"]
        assert isinstance(reset, str) and reset, f"重置后应为非空随机默认昵称: {resp.text}"
    finally:
        api_client.put("/api/user/nickname", json={"nickname": original})
