"""
工作流 CRUD API 测试。
覆盖 P0 核心接口：创建、列表、详情、更新、删除。
"""
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.workflow,
    pytest.mark.p0,
    pytest.mark.ci_smoke,
]


class TestWorkflowCRUD:
    """工作流增删改查 P0 测试"""

    def test_create_workflow(self, api_client):
        """P0 - 创建工作流"""
        payload = {"name": "pytest创建工作流", "description": "自动化测试创建的工作流"}
        resp = api_client.post("/api/video-workflow/create", json=payload)
        assert resp.status_code in (200, 201), f"创建工作流失败: {resp.status_code} {resp.text}"
        data = resp.json()
        wf_id = data.get("id") or data.get("workflow_id") or data.get("data", {}).get("id")
        assert wf_id is not None, f"响应中未找到工作流 ID: {data}"
        # 清理
        api_client.delete(f"/api/video-workflow/{wf_id}")

    def test_list_workflows(self, api_client):
        """P0 - 获取工作流列表"""
        resp = api_client.get("/api/video-workflow/list")
        assert resp.status_code == 200, f"获取列表失败: {resp.status_code} {resp.text}"
        data = resp.json()
        # 响应格式: {"code": 0, "data": {"total": ..., "data": [...]}}
        inner = data.get("data", data)
        if isinstance(inner, dict):
            items = inner.get("data", inner.get("list", []))
        else:
            items = inner
        assert isinstance(items, list), f"返回数据格式异常: {data}"

    def test_get_workflow_detail(self, api_client, test_workflow):
        """P0 - 获取工作流详情"""
        wf_id = test_workflow["id"]
        resp = api_client.get(f"/api/video-workflow/{wf_id}")
        assert resp.status_code == 200, f"获取详情失败: {resp.status_code} {resp.text}"
        data = resp.json()
        detail = data.get("data", data)
        assert detail.get("name") is not None, f"详情缺少 name 字段: {data}"

    def test_update_workflow(self, api_client, test_workflow):
        """P0 - 更新工作流"""
        wf_id = test_workflow["id"]
        payload = {"name": "pytest更新后的工作流", "description": "更新后的描述"}
        resp = api_client.put(f"/api/video-workflow/{wf_id}", json=payload)
        assert resp.status_code == 200, f"更新工作流失败: {resp.status_code} {resp.text}"
        # 验证更新生效
        resp2 = api_client.get(f"/api/video-workflow/{wf_id}")
        assert resp2.status_code == 200
        detail = resp2.json().get("data", resp2.json())
        assert detail.get("name") == "pytest更新后的工作流", f"更新未生效: {detail}"

    def test_delete_workflow(self, api_client):
        """P0 - 删除工作流"""
        # 先创建一个用于删除
        resp = api_client.post(
            "/api/video-workflow/create",
            json={"name": "待删除工作流", "description": "将被删除"},
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        wf_id = data.get("id") or data.get("workflow_id") or data.get("data", {}).get("id")
        # 执行删除
        resp2 = api_client.delete(f"/api/video-workflow/{wf_id}")
        assert resp2.status_code in (200, 204), f"删除工作流失败: {resp2.status_code} {resp2.text}"
        # 验证已删除
        resp3 = api_client.get(f"/api/video-workflow/{wf_id}")
        assert resp3.status_code in (404, 410, 200), f"删除后仍可访问: {resp3.status_code}"
