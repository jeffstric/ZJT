"""
世界管理 CRUD E2E 测试（P0）。

覆盖端点：
- POST   /api/worlds          创建世界
- GET    /api/worlds           世界列表
- PUT    /api/worlds/{id}      更新世界
- DELETE /api/worlds/{id}      删除世界（硬删除）
- POST   /api/worlds/{id}/hide     伪删除（隐藏）
- POST   /api/worlds/{id}/restore  恢复显示
"""
import time
import pytest


pytestmark = [pytest.mark.e2e, pytest.mark.world]


def _world_id_from_create(resp_json):
    return (
        resp_json.get("id")
        or resp_json.get("world_id")
        or resp_json.get("data", {}).get("id")
    )


def _worlds_from_list(resp_json):
    body = resp_json if isinstance(resp_json, dict) else {}
    inner = body.get("data", body)
    worlds = inner.get("data", []) if isinstance(inner, dict) else inner
    return worlds if isinstance(worlds, list) else []


# ────────────────── 创建 ──────────────────


@pytest.mark.p0
class TestWorldCreate:
    """POST /api/worlds"""

    def test_create_world(self, api_client):
        """P0: 创建世界，返回 200/201 且包含 id"""
        payload = {"name": "新建世界", "description": "用于创建测试"}
        resp = api_client.post("/api/worlds", json=payload)
        assert resp.status_code in (200, 201), f"创建世界失败: {resp.status_code} {resp.text}"

        data = resp.json()
        world_id = data.get("id") or data.get("world_id") or data.get("data", {}).get("id")
        assert world_id, f"响应中未找到世界 id: {data}"

        # 清理
        api_client.delete(f"/api/worlds/{world_id}")


# ────────────────── 列表 ──────────────────


@pytest.mark.p0
class TestWorldList:
    """GET /api/worlds"""

    def test_list_worlds(self, api_client, test_world):
        """P0: 获取世界列表，返回 200 且包含数据"""
        resp = api_client.get("/api/worlds")
        assert resp.status_code == 200, f"获取世界列表失败: {resp.status_code} {resp.text}"

        body = resp.json()
        # 响应格式: {"code": 0, "data": {"data": [...], "total": ...}}
        inner = body.get("data", body)
        worlds = inner.get("data", []) if isinstance(inner, dict) else inner
        assert isinstance(worlds, list), f"世界列表应为 list，实际: {type(worlds)}"


# ────────────────── 获取详情（从列表中查找） ──────────────────


@pytest.mark.p0
class TestWorldDetail:
    """GET /api/worlds（从列表中定位目标世界）"""

    def test_get_world_detail(self, api_client, test_world):
        """P0: 从列表中查找刚创建的世界，验证 name 字段"""
        resp = api_client.get("/api/worlds")
        assert resp.status_code == 200

        body = resp.json()
        inner = body.get("data", body)
        worlds = inner.get("data", []) if isinstance(inner, dict) else inner

        target_id = test_world["id"]
        found = [w for w in worlds if str(w.get("id", "")) == str(target_id)]
        assert found, f"世界列表中未找到 id={target_id} 的世界"
        assert found[0].get("name") == "E2E测试世界"


# ────────────────── 更新 ──────────────────


@pytest.mark.p0
class TestWorldUpdate:
    """PUT /api/worlds/{id}"""

    def test_update_world(self, api_client, test_world):
        """P0: 更新世界名称，返回 200"""
        world_id = test_world["id"]
        payload = {"name": "已更新世界", "description": "更新后的描述"}
        resp = api_client.put(f"/api/worlds/{world_id}", json=payload)
        assert resp.status_code == 200, f"更新世界失败: {resp.status_code} {resp.text}"


# ────────────────── 删除 ──────────────────


@pytest.mark.p0
class TestWorldDelete:
    """DELETE /api/worlds/{id}"""

    def test_delete_world(self, api_client):
        """P0: 删除世界，返回 200"""
        # 先创建一个专门用于删除测试的世界
        create_resp = api_client.post(
            "/api/worlds",
            json={"name": "待删除世界", "description": "删除测试用"},
        )
        assert create_resp.status_code in (200, 201)
        data = create_resp.json()
        world_id = data.get("id") or data.get("world_id") or data.get("data", {}).get("id")
        assert world_id

        del_resp = api_client.delete(f"/api/worlds/{world_id}")
        assert del_resp.status_code in (200, 204), f"删除世界失败: {del_resp.status_code} {del_resp.text}"


# ────────────────── P1 测试 ──────────────────


class TestWorldGetById:
    """通过列表接口验证世界详情"""

    @pytest.mark.p1
    def test_get_world_by_id(self, api_client, test_world):
        """P1: 从列表中通过 ID 查找世界，验证 name 匹配"""
        world_id = test_world["id"]
        # 该 API 无 GET /api/worlds/{id} 端点，通过列表查找
        resp = api_client.get("/api/worlds?page=1&page_size=100")
        assert resp.status_code == 200, f"获取世界列表失败: {resp.status_code} {resp.text}"
        body = resp.json()
        inner = body.get("data", body)
        worlds = inner.get("data", []) if isinstance(inner, dict) else inner
        found = [w for w in worlds if str(w.get("id")) == str(world_id)]
        assert found, f"列表中未找到世界 id={world_id}"
        assert found[0].get("name") == "E2E测试世界", f"世界名称不匹配: {found[0]}"


class TestWorldNameEmpty:
    """POST /api/worlds - 空名称校验"""

    @pytest.mark.p1
    def test_world_name_empty(self, api_client):
        """P1: 空名称创建世界应返回非200"""
        resp = api_client.post("/api/worlds", json={"name": "", "description": "空名称测试"})
        assert resp.status_code != 200, "空名称创建世界应返回非200状态码"


# ────────────────── 伪删除 / 恢复 ──────────────────


@pytest.mark.p0
class TestWorldSoftDelete:
    """POST /api/worlds/{id}/hide 与 /restore"""

    def test_hide_restore_world(self, api_client):
        """P0: 伪删除后默认列表不可见，deleted 可见；恢复后回到默认列表"""
        name = f"伪删除世界_{int(time.time())}"
        create_resp = api_client.post(
            "/api/worlds",
            json={"name": name, "description": "soft delete e2e"},
        )
        assert create_resp.status_code in (200, 201), create_resp.text
        world_id = _world_id_from_create(create_resp.json())
        assert world_id

        hide_resp = api_client.post(f"/api/worlds/{world_id}/hide")
        assert hide_resp.status_code == 200, hide_resp.text
        hide_body = hide_resp.json()
        assert hide_body.get("code", 0) == 0

        # 默认列表（active）不应包含
        active_resp = api_client.get("/api/worlds", params={"page": 1, "page_size": 100})
        assert active_resp.status_code == 200
        active_ids = {str(w.get("id")) for w in _worlds_from_list(active_resp.json())}
        assert str(world_id) not in active_ids

        # deleted 列表应包含
        deleted_resp = api_client.get(
            "/api/worlds",
            params={"page": 1, "page_size": 100, "visibility": "deleted"},
        )
        assert deleted_resp.status_code == 200
        deleted_ids = {str(w.get("id")) for w in _worlds_from_list(deleted_resp.json())}
        assert str(world_id) in deleted_ids

        restore_resp = api_client.post(f"/api/worlds/{world_id}/restore")
        assert restore_resp.status_code == 200, restore_resp.text
        assert restore_resp.json().get("code", 0) == 0

        active_resp2 = api_client.get("/api/worlds", params={"page": 1, "page_size": 100})
        active_ids2 = {str(w.get("id")) for w in _worlds_from_list(active_resp2.json())}
        assert str(world_id) in active_ids2

        # 清理（硬删除）
        api_client.delete(f"/api/worlds/{world_id}")

    def test_restore_name_conflict(self, api_client):
        """P0: 恢复时若存在同名未删除世界应 400"""
        suffix = int(time.time())
        name = f"冲突名世界_{suffix}"

        r1 = api_client.post("/api/worlds", json={"name": name, "description": "a"})
        assert r1.status_code in (200, 201), r1.text
        id1 = _world_id_from_create(r1.json())

        # 隐藏第一个
        hide1 = api_client.post(f"/api/worlds/{id1}/hide")
        assert hide1.status_code == 200, hide1.text

        # 再创建一个同名未删除世界
        r2 = api_client.post("/api/worlds", json={"name": name, "description": "b"})
        assert r2.status_code in (200, 201), r2.text
        id2 = _world_id_from_create(r2.json())

        # 恢复第一个应冲突
        restore = api_client.post(f"/api/worlds/{id1}/restore")
        assert restore.status_code == 400, restore.text
        body = restore.json()
        assert body.get("code", -1) != 0
        assert "同名" in (body.get("message") or "")

        # 清理
        api_client.delete(f"/api/worlds/{id2}")
        # id1 仍为伪删除，硬删也可
        api_client.delete(f"/api/worlds/{id1}")
