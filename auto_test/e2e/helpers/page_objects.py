"""
Page Object 基类和通用页面对象，用于 Playwright 浏览器测试。
"""
from playwright.sync_api import Page, expect


class BasePage:
    """Page Object 基类"""

    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")

    def navigate(self, path: str = ""):
        url = f"{self.base_url}{path}"
        self.page.goto(url, wait_until="domcontentloaded")

    def wait_for_load(self, timeout: int = 10000):
        self.page.wait_for_load_state("domcontentloaded", timeout=timeout)

    def get_title(self) -> str:
        return self.page.title()

    def is_element_visible(self, selector: str, timeout: int = 5000) -> bool:
        try:
            self.page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

    def click_element(self, selector: str, timeout: int = 5000):
        self.page.click(selector, timeout=timeout)

    def fill_input(self, selector: str, value: str, timeout: int = 5000):
        self.page.fill(selector, value, timeout=timeout)

    def get_text(self, selector: str, timeout: int = 5000) -> str:
        self.page.wait_for_selector(selector, timeout=timeout)
        return self.page.text_content(selector) or ""

    def wait_for_text(self, text: str, timeout: int = 10000):
        self.page.wait_for_selector(f"text={text}", timeout=timeout)


class IndexPage(BasePage):
    """首页"""

    def navigate(self):
        super().navigate("/")

    def is_loaded(self) -> bool:
        return self.is_element_visible("body", timeout=10000)

    def click_marketing_mode(self):
        """点击营销模式入口"""
        self.click_element("text=营销", timeout=5000)


class ScriptWriterPage(BasePage):
    """剧本编辑器页面"""

    def navigate(self, user_id: str = "", world_id: str = ""):
        params = []
        if user_id:
            params.append(f"user_id={user_id}")
        if world_id:
            params.append(f"world_id={world_id}")
        qs = "&".join(params)
        path = f"/script-writer?{qs}" if qs else "/script-writer"
        super().navigate(path)

    def is_loaded(self) -> bool:
        return self.is_element_visible(".app-container", timeout=15000)

    def has_sidebar(self) -> bool:
        return self.is_element_visible(".file-sidebar", timeout=5000)

    def wait_for_session_ready(self):
        """等待会话初始化完成"""
        self.page.wait_for_selector("#session-id", timeout=15000)
        self.page.wait_for_timeout(2000)

    def send_message(self, text: str):
        """发送消息"""
        textarea = self.page.locator("#message-input")
        textarea.wait_for(state="visible", timeout=10000)
        textarea.click()
        textarea.fill(text)
        self.page.wait_for_timeout(200)
        self.page.locator("#send-btn").click()

    def get_message_count(self) -> int:
        """获取聊天消息数量"""
        return self.page.locator(".message").count()

    def get_session_id(self) -> str:
        """获取当前会话 ID"""
        el = self.page.locator("#session-id")
        el.wait_for(state="visible", timeout=10000)
        return el.text_content() or ""

    def switch_file_tab(self, tab_type: str):
        """切换文件 Tab (worlds/characters/scripts/locations/props)"""
        self.page.locator(f".tab-btn[data-type='{tab_type}']").click()
        self.page.wait_for_timeout(500)

    def get_file_tab_count(self) -> int:
        """获取文件 Tab 数量"""
        return self.page.locator(".tab-btn").count()

    def mock_computing_power(self, power: int = 9999):
        """拦截算力 API 防止重定向"""
        import json as _json

        def handler(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"success": True, "data": {"computing_power": power}}),
            )

        self.page.route("**/api/user/computing_power", handler)


class WorkflowListPage(BasePage):
    """工作流列表页面"""

    def navigate(self):
        super().navigate("/video-workflow-list")

    def is_loaded(self) -> bool:
        return self.is_element_visible("body", timeout=10000)

    def has_create_button(self) -> bool:
        return self.is_element_visible(
            "button:has-text('新建'), button:has-text('创建'), [class*='create']",
            timeout=5000,
        )


class WorkflowEditorPage(BasePage):
    """工作流编辑器页面"""

    def navigate(self, workflow_id: str = ""):
        path = f"/video-workflow?id={workflow_id}" if workflow_id else "/video-workflow"
        super().navigate(path)

    def is_loaded(self) -> bool:
        return self.is_element_visible("body", timeout=10000)

    def has_canvas(self) -> bool:
        return self.is_element_visible("canvas, [class*='canvas']", timeout=5000)


class MarketingAgentPage(BasePage):
    """营销智能体页面"""

    def navigate(self):
        super().navigate("/marketing-agent")

    def is_loaded(self) -> bool:
        return self.is_element_visible("body", timeout=10000)

    def has_sidebar(self) -> bool:
        return self.is_element_visible(
            "[class*='sidebar'], [class*='session']", timeout=5000
        )

    def has_input_area(self) -> bool:
        return self.is_element_visible(
            "textarea, input[type='text'], [class*='input']", timeout=5000
        )

    def wait_for_sidebar_loaded(self):
        """等待侧边栏会话列表加载

        30s：全量套件长跑时浏览器负载高，页面渲染可能超过 10s（曾造成 flake）。
        """
        self.page.wait_for_selector(
            ".sidebar-history-item, .new-chat-btn", timeout=30000
        )

    def send_message(self, text: str):
        """发送消息（处理 Vue v-model 和遮挡问题）"""
        textarea = self.page.locator(".marketing-textarea").first
        textarea.wait_for(state="visible", timeout=10000)
        textarea.click()
        self.page.wait_for_timeout(200)
        textarea.fill(text)
        # 触发 Vue v-model 更新
        self.page.evaluate("""(text) => {
            const ta = document.querySelector('.marketing-textarea');
            if (ta) {
                // 设置原生值
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(ta, text);
                ta.dispatchEvent(new Event('input', { bubbles: true }));
                ta.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }""", text)
        self.page.wait_for_timeout(500)
        # 隐藏遮挡元素
        self.page.evaluate("""() => {
            const fab = document.querySelector('.feedback-fab-container');
            if (fab) {
                fab.style.display = 'none';
                fab.style.pointerEvents = 'none';
            }
        }""")
        # 点击发送按钮
        send_btn = self.page.locator(".marketing-send-btn").first
        send_btn.wait_for(state="visible", timeout=5000)
        send_btn.click()

    def get_session_count(self) -> int:
        """获取侧边栏会话数量"""
        return self.page.locator(".sidebar-history-item").count()

    def click_new_chat(self):
        """点击新建会话按钮"""
        self.page.locator(".new-chat-btn").first.click()
        self.page.wait_for_timeout(1500)

    def switch_session(self, index: int):
        """切换到指定索引的会话"""
        self.page.locator(".sidebar-history-item").nth(index).click()
        self.page.wait_for_timeout(1000)

    def get_active_session_title(self) -> str:
        """获取当前活跃会话的标题"""
        el = self.page.locator(".sidebar-history-item.active .history-title").first
        el.wait_for(state="visible", timeout=5000)
        return el.text_content() or ""

    def mock_computing_power(self, power: int = 9999):
        """拦截算力 API 防止重定向"""
        import json as _json

        def handler(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"success": True, "data": {"computing_power": power}}),
            )

        self.page.route("**/api/user/computing_power", handler)


class AdminPage(BasePage):
    """管理后台页面（Vue 3 SPA）"""

    def navigate(self):
        super().navigate("/admin")

    def is_loaded(self) -> bool:
        """管理后台加载完成（侧边栏 + 主内容区）"""
        return self.is_element_visible(".admin-sidebar", timeout=15000)

    def has_dashboard(self) -> bool:
        return self.is_element_visible(".stats-grid", timeout=10000)

    # ── 页面切换 ──
    def switch_page(self, page_name: str):
        """切换侧边栏页面 (dashboard/users/config/checkin/implementations/notifications)"""
        self.page.locator(f".admin-nav a").filter(
            has_text=self._nav_text(page_name)
        ).click()
        self.page.wait_for_timeout(1000)

    def _nav_text(self, page_name: str) -> str:
        """返回导航链接中的文本片段"""
        mapping = {
            "dashboard": "仪表盘",
            "users": "用户管理",
            "config": "系统配置",
            "checkin": "签到管理",
            "implementations": "实现方管理",
            "notifications": "通知中心",
        }
        return mapping.get(page_name, page_name)

    def get_current_page(self) -> str:
        """获取当前页面标题"""
        h2 = self.page.locator(".admin-header h2")
        return h2.text_content() or ""

    # ── 仪表盘 ──
    def get_stat_card_value(self, label_text: str) -> str:
        """获取统计卡片的值"""
        card = self.page.locator(".stat-card").filter(has_text=label_text)
        if card.count() == 0:
            return ""
        val = card.locator(".stat-card-value")
        return val.text_content() or ""

    def get_stat_card_count(self) -> int:
        return self.page.locator(".stat-card").count()

    # ── 用户管理 ──
    def search_users(self, keyword: str = "", status: str = "", role: str = ""):
        """搜索用户"""
        if keyword:
            inp = self.page.locator(".table-filters .filter-input").first
            inp.fill(keyword)
        if status:
            self.page.locator(".filter-select").nth(0).select_option(status)
        if role:
            self.page.locator(".filter-select").nth(1).select_option(role)
        self.page.locator(".filter-btn").first.click()
        self.page.wait_for_timeout(1000)

    def get_user_table_rows(self) -> int:
        """获取用户表格行数"""
        return self.page.locator(".admin-table tbody tr").count()

    def get_user_row_text(self, row_index: int = 0) -> str:
        """获取指定行的文本"""
        row = self.page.locator(".admin-table tbody tr").nth(row_index)
        return row.text_content() or ""

    def click_user_action(self, row_index: int, button_text: str):
        """点击用户行中的操作按钮"""
        row = self.page.locator(".admin-table tbody tr").nth(row_index)
        row.locator(f"button:has-text('{button_text}')").click()
        self.page.wait_for_timeout(500)

    def get_pagination_info(self) -> str:
        """获取分页信息"""
        info = self.page.locator(".page-info")
        return info.text_content() or ""

    # ── 系统配置 ──
    def search_configs(self, keyword: str = ""):
        """搜索配置"""
        if keyword:
            self.page.locator(".table-filters .filter-input").first.fill(keyword)
        self.page.locator(".filter-btn").first.click()
        self.page.wait_for_timeout(1000)

    def get_config_table_rows(self) -> int:
        return self.page.locator(".admin-table tbody tr").count()

    def click_config_edit(self, row_index: int = 0):
        """点击配置行的编辑按钮"""
        row = self.page.locator(".admin-table tbody tr").nth(row_index)
        row.locator("button:has-text('编辑')").click()
        self.page.wait_for_timeout(500)

    def get_modal_visible(self) -> bool:
        """检查模态框是否可见"""
        return self.page.locator(".modal-overlay").count() > 0

    def close_modal(self):
        """关闭模态框"""
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(300)

    def get_toast_text(self) -> str:
        """获取 toast 消息"""
        toast = self.page.locator(".toast")
        if toast.count() > 0:
            return toast.text_content() or ""
        return ""
