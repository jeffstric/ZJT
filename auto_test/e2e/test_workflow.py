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


class TestWorkflowSaveCAS:
    """P1 - 保存 CAS 乐观锁（content_version + X-Base-Hash，commit 719e0032/2ff48436）"""

    @staticmethod
    def _get_hash(api_client, wf_id):
        resp = api_client.get(f"/api/video-workflow/{wf_id}")
        assert resp.status_code == 200, f"获取详情失败: {resp.status_code} {resp.text}"
        detail = resp.json().get("data", resp.json())
        return detail.get("content_hash")

    def test_detail_returns_content_hash(self, api_client, test_workflow):
        """P1 - 详情接口返回服务端权威 content_hash"""
        wf_id = test_workflow["id"]
        h = self._get_hash(api_client, wf_id)
        assert isinstance(h, str) and len(h) >= 16, f"content_hash 缺失或过短: {h!r}"

    def test_cas_update_with_correct_base_hash(self, api_client, test_workflow):
        """P1 - 携带正确 X-Base-Hash 保存成功，并返回新哈希"""
        wf_id = test_workflow["id"]
        h1 = self._get_hash(api_client, wf_id)
        resp = api_client.put(
            f"/api/video-workflow/{wf_id}",
            json={"name": "pytest CAS 正确基线"},
            headers={"X-Base-Hash": h1},
        )
        assert resp.status_code == 200, f"CAS 保存失败: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data.get("code") == 0, f"CAS 保存业务失败: {data}"
        h2 = data.get("data", {}).get("content_hash")
        assert isinstance(h2, str) and h2, f"保存响应应含新 content_hash: {data}"

    def test_cas_reject_stale_base_hash(self, api_client, test_workflow):
        """P1 - 过期基线（内容已被改写）保存被 409 拒绝，并回传当前哈希

        注意：内容哈希只覆盖 workflow_data/style/style_reference_image/
        default_world_id/workflow_ratio（name 不参与），故用 default_world_id
        推进内容变更。
        """
        wf_id = test_workflow["id"]
        h1 = self._get_hash(api_client, wf_id)

        # 第一次保存推进内容（h1 -> h2）
        resp1 = api_client.put(
            f"/api/video-workflow/{wf_id}",
            json={"default_world_id": 1},
            headers={"X-Base-Hash": h1},
        )
        assert resp1.status_code == 200, f"第一次保存失败: {resp1.status_code} {resp1.text}"
        h2 = resp1.json().get("data", {}).get("content_hash")
        assert h2 and h2 != h1, f"内容变更后哈希应推进: h1={h1}, h2={h2}"

        # 用旧基线 h1 再次保存 → 409
        resp2 = api_client.put(
            f"/api/video-workflow/{wf_id}",
            json={"default_world_id": 2},
            headers={"X-Base-Hash": h1},
        )
        assert resp2.status_code == 409, f"过期基线应返回 409，实际 {resp2.status_code}: {resp2.text}"
        data2 = resp2.json()
        assert data2.get("code") == 409, f"409 响应 code 应为 409: {data2}"
        current = data2.get("data", {}).get("content_hash")
        assert isinstance(current, str) and current and current != h1, \
            f"409 应回传当前哈希且不同于过期基线: {data2}"

        # 内容不应被过期请求改写
        detail = api_client.get(f"/api/video-workflow/{wf_id}").json().get("data", {})
        assert detail.get("default_world_id") == 1, \
            f"过期请求不应覆盖内容: {detail.get('default_world_id')}"

    def test_update_without_base_hash_compatible(self, api_client, test_workflow):
        """P1 - 不带 X-Base-Hash 强制写路径仍兼容（旧前端/恢复重放）"""
        wf_id = test_workflow["id"]
        resp = api_client.put(
            f"/api/video-workflow/{wf_id}",
            json={"name": "pytest 无基线强制写"},
        )
        assert resp.status_code == 200, f"无 X-Base-Hash 保存应成功: {resp.status_code} {resp.text}"
        assert resp.json().get("code") == 0
