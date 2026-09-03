"""
工作流前端页面 E2E 测试。
使用 Playwright + Page Object 验证页面加载与基本交互。
"""
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.workflow_page,
    pytest.mark.p0,
    pytest.mark.ci_smoke,
]


class TestWorkflowPage:
    """工作流页面 P0 测试"""

    def test_workflow_list_page_loads(self, workflow_list_page):
        """P0 - 工作流列表页正常加载"""
        workflow_list_page.navigate()
        workflow_list_page.wait_for_load()
        assert workflow_list_page.is_loaded(), "工作流列表页未能正常加载"

    def test_workflow_editor_page_loads(self, workflow_editor_page):
        """P0 - 工作流编辑器页正常加载"""
        workflow_editor_page.navigate()
        workflow_editor_page.wait_for_load()
        assert workflow_editor_page.is_loaded(), "工作流编辑器页未能正常加载"

    def test_create_workflow_from_ui(self, workflow_list_page, page, base_url):
        """P0 - 从列表页点击新建按钮，跳转到编辑器"""
        workflow_list_page.navigate()
        workflow_list_page.wait_for_load()
        assert workflow_list_page.has_create_button(), "列表页缺少新建按钮"
        workflow_list_page.click_element(
            "button:has-text('新建'), button:has-text('创建'), [class*='create']"
        )
        # 等待跳转到编辑器页面
        page.wait_for_url("**/video-workflow*", timeout=10000)
        assert "/video-workflow" in page.url, f"未跳转到编辑器页: {page.url}"
