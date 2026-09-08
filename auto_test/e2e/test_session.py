"""会话管理模块 E2E 测试"""
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.session,
    pytest.mark.p0,
    pytest.mark.ci_smoke,
]


class TestSession:
    """会话管理 CRUD 测试"""

    def test_session_create(self, api_client, auth_token, user_id):
        """创建会话成功"""
        # 先获取一个世界 ID
        worlds_resp = api_client.get("/api/worlds")
        worlds_data = worlds_resp.json()
        inner = worlds_data.get("data", worlds_data)
        worlds = inner.get("data", []) if isinstance(inner, dict) else inner
        world_id = worlds[0]["id"] if worlds else "1"

        resp = api_client.post(
            "/api/session/create",
            json={
                "user_id": str(user_id),
                "world_id": str(world_id),
                "auth_token": auth_token,
                "session_type": 1,
            },
        )
        assert resp.status_code in (200, 201), f"创建会话失败: {resp.status_code} {resp.text}"
        data = resp.json()
        session_id = data.get("session_id") or data.get("id") or data.get("data", {}).get("session_id")
        assert session_id, f"创建会话响应中未找到 session_id: {data}"
        # 清理
        try:
            api_client.delete(f"/api/session/{session_id}")
        except Exception:
            pass

    def test_session_list(self, api_client, test_session_id):
        """获取会话列表"""
        resp = api_client.get("/api/sessions", timeout=15)
        assert resp.status_code == 200, f"获取会话列表失败: {resp.status_code}"
        data = resp.json()
        # 响应可能是列表或包含列表的字典
        sessions = data if isinstance(data, list) else data.get("sessions", data.get("data", []))
        if isinstance(sessions, dict):
            sessions = sessions.get("data", [])
        assert isinstance(sessions, list), f"会话列表响应格式异常: {data}"

    def test_session_history(self, api_client, test_session_id):
        """获取会话历史记录"""
        resp = api_client.get(f"/api/session/{test_session_id}/history")
        assert resp.status_code == 200, f"获取会话历史失败: {resp.status_code} {resp.text}"
        data = resp.json()
        history = data if isinstance(data, list) else data.get("history", data.get("data", []))
        if isinstance(history, dict):
            history = history.get("data", [])
        assert isinstance(history, list), f"会话历史响应格式异常: {data}"

    def test_session_update_title(self, api_client, test_session_id):
        """更新会话标题"""
        new_title = "E2E测试更新标题"
        resp = api_client.put(
            f"/api/session/{test_session_id}/title",
            json={"title": new_title},
        )
        assert resp.status_code == 200, f"更新标题失败: {resp.status_code} {resp.text}"

    def test_session_delete(self, api_client, auth_token, user_id):
        """删除会话成功"""
        # 先获取一个世界 ID
        worlds_resp = api_client.get("/api/worlds")
        worlds_data = worlds_resp.json()
        inner = worlds_data.get("data", worlds_data)
        worlds = inner.get("data", []) if isinstance(inner, dict) else inner
        world_id = worlds[0]["id"] if worlds else "1"

        # 先创建一个会话用于删除测试
        create_resp = api_client.post(
            "/api/session/create",
            json={
                "user_id": str(user_id),
                "world_id": str(world_id),
                "auth_token": auth_token,
                "session_type": 1,
            },
        )
        assert create_resp.status_code in (200, 201), f"创建会话失败: {create_resp.status_code} {create_resp.text}"
        data = create_resp.json()
        session_id = data.get("session_id") or data.get("id") or data.get("data", {}).get("session_id")
        assert session_id, f"创建会话失败，无法测试删除: {data}"

        # 执行删除
        del_resp = api_client.delete(f"/api/session/{session_id}")
        assert del_resp.status_code in (200, 204), f"删除会话失败: {del_resp.status_code} {del_resp.text}"
