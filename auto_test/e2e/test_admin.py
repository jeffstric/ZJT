"""
管理后台页面 E2E 测试。
覆盖页面加载、仪表盘、用户管理、系统配置、签到管理、实现方管理、通知中心等场景。

注意：/admin 页面需要管理员权限。
使用 admin_browser_page fixture 提供带认证的页面实例。
"""
import time

import pytest


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def _navigate_admin(ap, wait_dashboard=True):
    """导航到管理后台并等待加载"""
    ap.navigate()
    ap.page.wait_for_timeout(3000)
    if wait_dashboard:
        try:
            ap.page.wait_for_selector(".stats-grid, .admin-table", timeout=10000)
        except Exception:
            ap.page.wait_for_timeout(2000)


# ═══════════════════════════════════════════════════════════════
# P0 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.admin
def test_admin_page_loads(admin_browser_page):
    """admin_001 - 管理后台页面加载成功。"""
    _navigate_admin(admin_browser_page, wait_dashboard=False)
    assert admin_browser_page.is_loaded(), "管理后台页面未正常加载"
    # 验证侧边栏存在
    assert admin_browser_page.page.locator(".admin-sidebar").count() > 0, "缺少侧边栏"
    assert admin_browser_page.page.locator(".admin-nav").count() > 0, "缺少导航菜单"


@pytest.mark.p0
@pytest.mark.admin
def test_admin_sidebar_navigation(admin_browser_page):
    """admin_002 - 侧边栏导航可切换页面。"""
    _navigate_admin(admin_browser_page)
    page = admin_browser_page.page

    # 验证导航项存在
    nav_items = page.locator(".admin-nav li")
    assert nav_items.count() >= 6, f"应有 6 个导航项，实际 {nav_items.count()}"

    # 切换到用户管理
    admin_browser_page.switch_page("users")
    assert "用户" in admin_browser_page.get_current_page(), "应切换到用户管理页面"

    # 切换到系统配置
    admin_browser_page.switch_page("config")
    assert "配置" in admin_browser_page.get_current_page(), "应切换到系统配置页面"

    # 切回仪表盘
    admin_browser_page.switch_page("dashboard")
    assert "仪表盘" in admin_browser_page.get_current_page(), "应切回仪表盘"


@pytest.mark.p0
@pytest.mark.admin
def test_admin_dashboard_stats(admin_browser_page):
    """admin_003 - 仪表盘显示统计数据。"""
    _navigate_admin(admin_browser_page)
    page = admin_browser_page.page

    # 等待加载完成
    page.wait_for_selector(".stats-grid", timeout=15000)

    # 验证统计卡片
    stat_cards = page.locator(".stat-card")
    assert stat_cards.count() >= 3, f"应有至少 3 个统计卡片，实际 {stat_cards.count()}"

    # 验证用户总数有值
    total = admin_browser_page.get_stat_card_value("用户总数")
    assert total and total != "-", f"用户总数应有值，实际: '{total}'"


@pytest.mark.p0
@pytest.mark.admin
def test_admin_dashboard_model_analysis(admin_browser_page):
    """admin_004 - 仪表盘模型成功率分析表格。"""
    _navigate_admin(admin_browser_page)
    page = admin_browser_page.page

    # 等待模型分析加载
    page.wait_for_timeout(3000)

    # 检查是否有模型分析区域
    section = page.locator(".model-analysis-section")
    if section.count() == 0:
        pytest.skip("模型分析区域不存在")

    # 检查时间范围标签
    tabs = page.locator(".time-range-tabs button")
    assert tabs.count() >= 3, "应有 3 个时间范围标签（今天/3天/7天）"


@pytest.mark.p0
@pytest.mark.admin
def test_admin_user_list(admin_browser_page):
    """admin_005 - 用户管理页面显示用户列表。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("users")
    page = admin_browser_page.page

    # 等待表格加载
    page.wait_for_selector(".admin-table", timeout=10000)

    # 验证表格存在
    rows = admin_browser_page.get_user_table_rows()
    assert rows > 0, "用户列表不应为空"

    # 验证表头
    headers = page.locator(".admin-table thead th")
    assert headers.count() >= 6, f"应有至少 6 列，实际 {headers.count()}"


@pytest.mark.p0
@pytest.mark.admin
def test_admin_user_search(admin_browser_page):
    """admin_006 - 用户搜索功能。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("users")
    page = admin_browser_page.page

    page.wait_for_selector(".admin-table", timeout=10000)

    # 搜索筛选区域存在
    filters = page.locator(".table-filters")
    assert filters.count() > 0, "搜索筛选区域应存在"

    # 状态筛选
    status_select = page.locator(".filter-select").first
    assert status_select.count() > 0, "状态筛选下拉框应存在"

    # 角色筛选
    role_select = page.locator(".filter-select").nth(1)
    assert role_select.count() > 0, "角色筛选下拉框应存在"


@pytest.mark.p0
@pytest.mark.admin
def test_admin_config_list(admin_browser_page):
    """admin_007 - 系统配置页面显示配置列表。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("config")
    page = admin_browser_page.page

    page.wait_for_selector(".admin-table", timeout=10000)

    # 验证配置表格
    rows = admin_browser_page.get_config_table_rows()
    assert rows > 0, "配置列表不应为空"

    # 验证操作按钮
    action_btns = page.locator(".table-actions .action-btn")
    assert action_btns.count() >= 2, "应有初始化和重载按钮"


@pytest.mark.p0
@pytest.mark.admin
def test_admin_user_detail_modal(admin_browser_page):
    """admin_008 - 点击查看详情打开用户详情模态框。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("users")
    page = admin_browser_page.page

    page.wait_for_selector(".admin-table tbody tr", timeout=10000)

    # 点击第一行的"详情"按钮
    admin_browser_page.click_user_action(0, "详情")
    page.wait_for_timeout(500)

    # 验证模态框出现
    modal = page.locator(".modal-overlay")
    assert modal.count() > 0, "用户详情模态框应出现"

    # 验证模态框内容
    modal_body = page.locator(".modal-body")
    text = modal_body.text_content() or ""
    assert "用户" in text or "ID" in text, f"模态框应显示用户信息"

    # 关闭
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


@pytest.mark.p0
@pytest.mark.admin
def test_admin_power_adjust_modal(admin_browser_page):
    """admin_009 - 点击调整算力打开算力调整模态框。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("users")
    page = admin_browser_page.page

    page.wait_for_selector(".admin-table tbody tr", timeout=10000)

    # 点击"调整算力"
    admin_browser_page.click_user_action(0, "调整算力")
    page.wait_for_timeout(500)

    modal = page.locator(".modal-overlay")
    assert modal.count() > 0, "算力调整模态框应出现"

    # 验证表单字段
    form_groups = page.locator(".modal-body .form-group")
    assert form_groups.count() >= 3, "应有用户、当前算力、调整金额等字段"

    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


# ═══════════════════════════════════════════════════════════════
# P1 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p1
@pytest.mark.admin
def test_admin_user_pagination(admin_browser_page):
    """admin_010 - 用户列表分页功能。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("users")
    page = admin_browser_page.page

    page.wait_for_selector(".admin-table", timeout=10000)

    # 检查分页区域
    pagination = page.locator(".pagination")
    if pagination.count() == 0:
        # 用户少时可能没有分页
        rows = admin_browser_page.get_user_table_rows()
        assert rows > 0, "无分页时应有用户数据"
        return

    # 验证分页按钮
    page_btns = page.locator(".page-btn")
    assert page_btns.count() >= 4, "应有首页/上一页/下一页/末页按钮"


@pytest.mark.p1
@pytest.mark.admin
def test_admin_config_edit_modal(admin_browser_page):
    """admin_011 - 点击编辑打开配置编辑模态框。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("config")
    page = admin_browser_page.page

    page.wait_for_selector(".admin-table tbody tr", timeout=10000)

    # 找到可编辑的配置行
    edit_btns = page.locator(".admin-table tbody tr button:has-text('编辑')")
    if edit_btns.count() == 0:
        pytest.skip("没有可编辑的配置")

    edit_btns.first.click()
    page.wait_for_timeout(500)

    modal = page.locator(".modal-overlay")
    assert modal.count() > 0, "配置编辑模态框应出现"

    # 验证模态框标题
    header = page.locator(".modal-header h3")
    text = header.text_content() or ""
    assert "编辑" in text or "配置" in text, f"模态框标题应包含编辑/配置"

    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


@pytest.mark.p1
@pytest.mark.admin
def test_admin_config_history_modal(admin_browser_page):
    """admin_012 - 点击历史打开配置历史模态框。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("config")
    page = admin_browser_page.page

    page.wait_for_selector(".admin-table tbody tr", timeout=10000)

    history_btns = page.locator(".admin-table tbody tr button:has-text('历史')")
    if history_btns.count() == 0:
        pytest.skip("没有历史按钮")

    history_btns.first.click()
    page.wait_for_timeout(1000)

    modal = page.locator(".modal-overlay")
    assert modal.count() > 0, "配置历史模态框应出现"

    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


@pytest.mark.p1
@pytest.mark.admin
def test_admin_checkin_page(admin_browser_page):
    """admin_013 - 签到管理页面加载。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("checkin")
    page = admin_browser_page.page

    page.wait_for_timeout(2000)

    # 验证签到配置表单
    form = page.locator(".checkin-config-form")
    if form.count() == 0:
        # 可能是 loading 状态
        page.wait_for_timeout(3000)
        form = page.locator(".checkin-config-form")

    assert form.count() > 0, "签到配置表单应存在"


@pytest.mark.p1
@pytest.mark.admin
def test_admin_implementations_page(admin_browser_page):
    """admin_014 - 实现方管理页面加载。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("implementations")
    page = admin_browser_page.page

    page.wait_for_timeout(3000)

    # 验证实现方分组
    groups = page.locator(".implementation-group")
    assert groups.count() > 0, "应有实现方分组"

    # 验证排序输入框
    sort_inputs = page.locator(".sort-input")
    assert sort_inputs.count() > 0, "应有排序输入框"


@pytest.mark.p1
@pytest.mark.admin
def test_admin_notifications_page(admin_browser_page):
    """admin_015 - 通知中心页面加载。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("notifications")
    page = admin_browser_page.page

    page.wait_for_timeout(2000)

    # 验证通知容器
    container = page.locator(".table-container")
    assert container.count() > 0, "通知容器应存在"

    # 验证"全部已读"按钮
    mark_btn = page.locator("button:has-text('全部已读')")
    assert mark_btn.count() > 0, "应有全部已读按钮"


@pytest.mark.p1
@pytest.mark.admin
def test_admin_user_status_filter(admin_browser_page):
    """admin_016 - 用户状态筛选。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("users")
    page = admin_browser_page.page

    page.wait_for_selector(".admin-table", timeout=10000)

    # 筛选正常用户
    status_select = page.locator(".filter-select").first
    status_select.select_option("1")
    page.wait_for_timeout(1000)

    # 验证表格仍有数据（或显示无数据）
    table = page.locator(".admin-table")
    assert table.count() > 0, "筛选后表格应存在"


@pytest.mark.p1
@pytest.mark.admin
def test_admin_user_role_filter(admin_browser_page):
    """admin_017 - 用户角色筛选。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("users")
    page = admin_browser_page.page

    page.wait_for_selector(".admin-table", timeout=10000)

    # 筛选管理员
    role_select = page.locator(".filter-select").nth(1)
    role_select.select_option("admin")
    page.wait_for_timeout(1000)

    table = page.locator(".admin-table")
    assert table.count() > 0, "筛选后表格应存在"


@pytest.mark.p1
@pytest.mark.admin
def test_admin_model_analysis_time_range(admin_browser_page):
    """admin_018 - 模型分析时间范围切换。"""
    _navigate_admin(admin_browser_page)
    page = admin_browser_page.page

    page.wait_for_timeout(3000)

    section = page.locator(".model-analysis-section")
    if section.count() == 0:
        pytest.skip("模型分析区域不存在")

    # 点击"今天"
    tabs = page.locator(".time-range-tabs button")
    if tabs.count() >= 1:
        tabs.nth(0).click()
        page.wait_for_timeout(1000)
        assert "active" in (tabs.nth(0).get_attribute("class") or ""), "今天标签应为 active"

    # 点击"7天"
    if tabs.count() >= 3:
        tabs.nth(2).click()
        page.wait_for_timeout(1000)
        assert "active" in (tabs.nth(2).get_attribute("class") or ""), "7天标签应为 active"


@pytest.mark.p1
@pytest.mark.admin
def test_admin_monthly_active_users_query(admin_browser_page):
    """admin_019 - 月活用户查询按钮。"""
    _navigate_admin(admin_browser_page)
    page = admin_browser_page.page

    page.wait_for_selector(".stats-grid", timeout=15000)

    # 找到月活用户卡片的查询按钮
    query_btn = page.locator(".stat-card-actions .action-btn")
    if query_btn.count() == 0:
        pytest.skip("月活查询按钮不存在")

    query_btn.first.click()
    page.wait_for_timeout(3000)

    # 验证结果有值（或仍在加载）
    value_el = page.locator(".stat-card-value").nth(2)
    assert value_el.count() > 0, "月活用户值应存在"


@pytest.mark.p1
@pytest.mark.admin
def test_admin_logout_button(admin_browser_page):
    """admin_020 - 登出按钮存在。"""
    _navigate_admin(admin_browser_page)
    page = admin_browser_page.page

    logout_btn = page.locator(".admin-logout")
    assert logout_btn.count() > 0, "登出按钮应存在"
    text = logout_btn.text_content() or ""
    assert "退出" in text or "登出" in text or "logout" in text.lower(), f"按钮文本应包含退出/登出"


@pytest.mark.p1
@pytest.mark.admin
def test_admin_version_display(admin_browser_page):
    """admin_021 - 底部显示版本信息。"""
    _navigate_admin(admin_browser_page)
    page = admin_browser_page.page

    footer = page.locator(".admin-footer")
    assert footer.count() > 0, "底部栏应存在"

    text = footer.text_content() or ""
    assert text.strip(), f"底部栏应有内容"


@pytest.mark.p1
@pytest.mark.admin
def test_admin_back_to_home(admin_browser_page):
    """admin_022 - 侧边栏有返回首页链接。"""
    _navigate_admin(admin_browser_page)
    page = admin_browser_page.page

    back_link = page.locator(".admin-nav a[href='/']")
    assert back_link.count() > 0, "返回首页链接应存在"


# ═══════════════════════════════════════════════════════════════
# P2 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p2
@pytest.mark.admin
def test_admin_config_search(admin_browser_page):
    """admin_023 - 配置搜索功能。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("config")
    page = admin_browser_page.page

    page.wait_for_selector(".admin-table", timeout=10000)

    # 搜索
    search_input = page.locator(".table-filters .filter-input").first
    search_input.fill("llm")
    page.locator(".filter-btn").first.click()
    page.wait_for_timeout(1000)

    # 验证有结果或无数据提示
    table = page.locator(".admin-table")
    assert table.count() > 0, "搜索后表格应存在"


@pytest.mark.p2
@pytest.mark.admin
def test_admin_config_reload(admin_browser_page):
    """admin_024 - 重载配置缓存按钮可点击。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("config")
    page = admin_browser_page.page

    page.wait_for_selector(".table-actions", timeout=10000)

    reload_btn = page.locator("button:has-text('重载缓存')")
    if reload_btn.count() == 0:
        pytest.skip("重载缓存按钮不存在")

    reload_btn.click()
    page.wait_for_timeout(2000)

    # 页面应仍然可用
    assert page.locator(".admin-table").count() > 0, "重载后页面应仍可用"


@pytest.mark.p2
@pytest.mark.admin
def test_admin_implementation_power_input(admin_browser_page):
    """admin_025 - 实现方算力输入框可编辑。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("implementations")
    page = admin_browser_page.page

    page.wait_for_timeout(3000)

    power_inputs = page.locator(".power-input")
    if power_inputs.count() == 0:
        pytest.skip("没有算力输入框")

    # 验证输入框存在且可见
    first_input = power_inputs.first
    assert first_input.is_visible(), "算力输入框应可见"


@pytest.mark.p2
@pytest.mark.admin
def test_admin_implementation_sort_input(admin_browser_page):
    """admin_026 - 实现方排序输入框可编辑。"""
    _navigate_admin(admin_browser_page)
    admin_browser_page.switch_page("implementations")
    page = admin_browser_page.page

    page.wait_for_timeout(3000)

    sort_inputs = page.locator(".sort-input")
    if sort_inputs.count() == 0:
        pytest.skip("没有排序输入框")

    first_input = sort_inputs.first
    assert first_input.is_visible(), "排序输入框应可见"


@pytest.mark.p2
@pytest.mark.admin
def test_admin_i18n_switcher(admin_browser_page):
    """admin_027 - 语言切换器存在。"""
    _navigate_admin(admin_browser_page)
    page = admin_browser_page.page

    switcher = page.locator("#i18nSwitcher")
    assert switcher.count() > 0, "语言切换器应存在"


@pytest.mark.p2
@pytest.mark.admin
def test_admin_responsive_layout(browser, live_auth, base_url):
    """admin_028 - 窄屏下页面仍可用。"""
    import json as _json

    live_auth.ensure()
    context = browser.new_context(
        viewport={"width": 375, "height": 667},
        locale="zh-CN",
    )
    context.add_init_script(f"""
        localStorage.setItem('auth_token', '{live_auth.token}');
        localStorage.setItem('user_id', '{live_auth.user_id}');
    """)
    p = context.new_page()

    # Mock admin API to avoid 401 redirect
    def _mock(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({"code": 0, "data": {"total_users": 10, "active_workflows_3d": 1}}),
        )

    p.route("**/api/admin/**", _mock)
    p.route("**/api/system/**", _mock)
    p.route("**/api/notifications/**", _mock)

    p.goto(f"{base_url}/admin", wait_until="domcontentloaded")
    p.wait_for_timeout(3000)

    assert p.locator(".admin-layout").count() > 0, "移动端应有 .admin-layout"

    p.close()
    context.close()
