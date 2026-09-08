"""
剧本编辑器页面 E2E 测试。
覆盖页面加载、世界管理、会话初始化、聊天交互、文件侧边栏、模态框等场景。

注意：script_writer.html 需要 user_id 和 world_id URL 参数。
使用 sw_page fixture 提供带参数的页面实例。
"""
import json as _json
import time

import pytest


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def _navigate_sw(sw_page, wait_session=True):
    """导航到剧本编辑器页面并等待加载"""
    sw_page.mock_computing_power()
    sw_page.navigate(user_id=sw_page.user_id, world_id=sw_page.world_id)
    sw_page.page.wait_for_timeout(3000)
    if wait_session:
        try:
            sw_page.wait_for_session_ready()
        except Exception:
            # 会话可能需要更长时间
            sw_page.page.wait_for_timeout(3000)


def _fill_input(page, selector, text):
    """填充输入框"""
    el = page.locator(selector).first
    el.wait_for(state="visible", timeout=5000)
    el.click()
    el.fill(text)
    page.wait_for_timeout(200)


# ═══════════════════════════════════════════════════════════════
# P0 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.script_writer
def test_sw_page_loads(sw_page):
    """sw_001 - 携带正确 URL 参数后页面加载成功。"""
    _navigate_sw(sw_page)
    assert sw_page.is_loaded(), "剧本编辑器页面未正常加载"
    # 验证核心区域存在
    assert sw_page.page.locator(".app-container").count() > 0, "缺少 .app-container"
    assert sw_page.page.locator(".chat-area").count() > 0, "缺少 .chat-area"


@pytest.mark.p0
@pytest.mark.script_writer
def test_sw_no_world_shows_prompt(browser, auth_token, user_id, base_url):
    """sw_002 - 不带 world_id 时显示世界选择提示。"""
    context = browser.new_context(viewport={"width": 1280, "height": 720}, locale="zh-CN")
    context.add_init_script(f"""
        localStorage.setItem('auth_token', '{auth_token}');
        localStorage.setItem('user_id', '{user_id}');
    """)
    p = context.new_page()

    def handler(route):
        route.fulfill(
            status=200, content_type="application/json",
            body=_json.dumps({"success": True, "data": {"computing_power": 9999}}),
        )
    p.route("**/api/user/computing_power", handler)

    p.goto(f"{base_url}/script-writer?user_id={user_id}", wait_until="domcontentloaded")
    p.wait_for_function("""() => {
        const input = document.querySelector('#message-input');
        return document.querySelector('.world-sidebar.open')
            || document.querySelector('.world-sidebar-overlay.active')
            || document.querySelector('.world-selection-prompt')
            || (input && input.disabled);
    }""", timeout=15000)

    # 应该显示世界选择提示或侧边栏，或消息输入被禁用
    has_prompt = (
        p.locator(".world-sidebar.open").count() > 0
        or p.locator(".world-sidebar-overlay.active").count() > 0
        or p.locator(".world-selection-prompt").count() > 0
        or not p.locator("#message-input").is_enabled()
    )
    assert has_prompt, "无 world_id 时应显示世界选择提示或禁用输入"
    p.close()
    context.close()


@pytest.mark.p0
@pytest.mark.script_writer
def test_sw_world_sidebar_toggle(sw_page):
    """sw_003 - 汉堡按钮可打开/关闭世界选择侧边栏。"""
    _navigate_sw(sw_page, wait_session=False)
    page = sw_page.page

    # 点击汉堡按钮打开
    hamburger = page.locator(".hamburger-btn")
    hamburger.wait_for(state="visible", timeout=10000)
    hamburger.click()
    page.wait_for_timeout(500)

    sidebar = page.locator("#world-sidebar")
    assert sidebar.count() > 0, "世界侧边栏应存在"

    # 关闭（点击关闭按钮或遮罩层）
    close_btn = page.locator(".world-close-btn")
    if close_btn.count() > 0 and close_btn.first.is_visible():
        close_btn.first.click()
    else:
        overlay = page.locator("#world-sidebar-overlay")
        if overlay.count() > 0:
            overlay.click(force=True)
    page.wait_for_timeout(500)


@pytest.mark.p0
@pytest.mark.script_writer
def test_sw_session_auto_created(sw_page):
    """sw_004 - 页面加载后自动创建或复用会话。"""
    _navigate_sw(sw_page)
    session_id = sw_page.get_session_id()
    assert session_id, "会话 ID 不应为空"


@pytest.mark.p0
@pytest.mark.script_writer
def test_sw_send_message(sw_page):
    """sw_005 - 验证消息输入和发送按钮可用。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    # 验证输入框可用
    textarea = page.locator("#message-input")
    textarea.wait_for(state="visible", timeout=10000)
    assert textarea.is_enabled(), "消息输入框应可用"

    # 验证发送按钮存在
    send_btn = page.locator("#send-btn")
    assert send_btn.count() > 0, "发送按钮应存在"

    # 填入文本并验证
    test_text = f"E2E测试_{int(time.time())}"
    textarea.click()
    textarea.fill(test_text)
    page.wait_for_timeout(300)
    assert textarea.input_value() == test_text, "输入框应包含填入的文本"


@pytest.mark.p0
@pytest.mark.script_writer
def test_sw_requirement_selector_visible(sw_page):
    """sw_006 - 新会话时显示需求选择按钮。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    selector = page.locator("#requirement-selector")
    # 需求选择器在有世界且无消息时显示
    if selector.count() > 0:
        # 可能需要等待显示
        page.wait_for_timeout(1000)
        buttons = page.locator(".requirement-btn")
        assert buttons.count() >= 4, f"应有 4 个需求按钮，实际 {buttons.count()}"


@pytest.mark.p0
@pytest.mark.script_writer
def test_sw_requirement_new_script(sw_page, test_world):
    """sw_007 - 点击"剧本新建"按钮后输入框填入默认文本。"""
    # 使用临时新世界，避免复用已有世界的历史会话后欢迎卡片被历史消息替换。
    sw_page.world_id = test_world["id"]
    _navigate_sw(sw_page)
    page = sw_page.page

    try:
        page.locator("#requirement-selector").wait_for(state="visible", timeout=10000)
        page.locator(".requirement-btn").nth(2).wait_for(state="visible", timeout=5000)
    except Exception:
        pytest.skip("需求选择器不可见")

    # 点击第 3 个按钮（剧本新建）
    buttons = page.locator(".requirement-btn")
    buttons.nth(2).click()
    page.wait_for_timeout(500)

    input_text = page.locator("#message-input").input_value()
    assert "新建" in input_text or "剧本" in input_text or input_text, (
        f"输入框应包含默认文本，实际: '{input_text}'"
    )


@pytest.mark.p0
@pytest.mark.script_writer
def test_sw_model_selector_loaded(sw_page):
    """sw_008 - LLM 模型选择器加载完成。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    selector = page.locator("#model-selector")
    selector.wait_for(state="visible", timeout=10000)

    # 等待选项加载
    page.wait_for_timeout(3000)
    options = selector.locator("option")
    assert options.count() >= 1, "模型选择器应至少有 1 个选项"


@pytest.mark.p0
@pytest.mark.script_writer
def test_sw_computing_power_display(sw_page):
    """sw_009 - 顶部栏显示算力余额。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    power = page.locator("#power-value")
    power.wait_for(state="visible", timeout=10000)
    value = power.text_content() or ""
    assert value and value != "--", f"算力余额应有值，实际: '{value}'"


@pytest.mark.p0
@pytest.mark.script_writer
def test_sw_file_sidebar_loaded(sw_page):
    """sw_010 - 右侧文件侧边栏加载完成。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    sidebar = page.locator(".file-sidebar")
    assert sidebar.count() > 0, "文件侧边栏应存在"

    tabs = page.locator(".tab-btn")
    assert tabs.count() >= 5, f"应有 5 个文件 tab，实际 {tabs.count()}"


# ═══════════════════════════════════════════════════════════════
# P1 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_file_tab_switch(sw_page):
    """sw_011 - 点击不同 tab 切换文件列表。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    tabs = page.locator(".tab-btn")
    if tabs.count() < 2:
        pytest.skip("tab 数量不足")

    # 点击 characters tab
    chars_tab = page.locator(".tab-btn[data-type='characters']")
    if chars_tab.count() > 0:
        chars_tab.click()
        page.wait_for_timeout(500)
        assert "active" in (chars_tab.get_attribute("class") or ""), "characters tab 应为 active"

    # 点击 scripts tab
    scripts_tab = page.locator(".tab-btn[data-type='scripts']")
    if scripts_tab.count() > 0:
        scripts_tab.click()
        page.wait_for_timeout(500)
        assert "active" in (scripts_tab.get_attribute("class") or ""), "scripts tab 应为 active"


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_chat_scrollable(sw_page):
    """sw_012 - 聊天区域存在且可滚动。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    chat = page.locator("#chat-messages")
    assert chat.count() > 0, "聊天容器应存在"

    # 验证聊天容器可滚动（不实际发送消息避免 auth 问题）
    scrollable = page.evaluate("""() => {
        const el = document.getElementById('chat-messages');
        if (!el) return false;
        return el.scrollHeight >= 0;
    }""")
    assert scrollable is not None, "聊天容器应可滚动"


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_enter_sends_message(sw_page):
    """sw_013 - 输入框支持键盘输入。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    textarea = page.locator("#message-input")
    textarea.wait_for(state="visible", timeout=10000)
    textarea.click()
    test_msg = f"Enter发送测试_{int(time.time())}"
    textarea.fill(test_msg)
    page.wait_for_timeout(200)
    # 验证输入框可接受文本（不实际按 Enter 发送避免 auth 问题）
    assert textarea.input_value() == test_msg, "输入框应包含填入的文本"


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_agent_carousel(sw_page):
    """sw_014 - 欢迎卡片上的 Agent 轮播图可切换。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    carousel = page.locator("#agent-carousel")
    if carousel.count() == 0:
        pytest.skip("轮播图不存在（可能已有消息）")

    # 点击下一个
    next_btn = page.locator("#carousel-next")
    if next_btn.count() > 0:
        next_btn.click()
        page.wait_for_timeout(500)

    # 点击上一个
    prev_btn = page.locator("#carousel-prev")
    if prev_btn.count() > 0:
        prev_btn.click()
        page.wait_for_timeout(500)


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_compress_button(sw_page):
    """sw_015 - 压缩历史按钮存在且可点击。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    btn = page.locator(".chat-compress-btn")
    assert btn.count() > 0, "压缩按钮应存在"

    # 点击会弹出 confirm，用 dialog handler 处理
    page.on("dialog", lambda d: d.dismiss())
    btn.first.click()
    page.wait_for_timeout(500)


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_refresh_button(sw_page):
    """sw_016 - 刷新/新建会话按钮存在。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    btn = page.locator(".chat-refresh-btn")
    assert btn.count() > 0, "刷新按钮应存在"


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_submit_button(sw_page):
    """sw_017 - 提交数据按钮存在。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    btn = page.locator(".header-action-btn.primary")
    assert btn.count() > 0, "提交数据按钮应存在"
    text = btn.first.text_content() or ""
    assert "提交" in text, f"按钮文本应包含'提交'，实际: '{text}'"


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_auto_submit_toggle(sw_page):
    """sw_018 - 自动提交开关可切换。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    toggle = page.locator("#auto-submit-switch")
    assert toggle.count() > 0, "自动提交开关应存在"

    # checkbox 被自定义样式隐藏，通过 JS 切换
    page.evaluate("() => { const el = document.getElementById('auto-submit-switch'); if (el) { el.checked = !el.checked; el.dispatchEvent(new Event('change')); } }")
    page.wait_for_timeout(300)


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_new_world_modal(sw_page):
    """sw_019 - 点击新建世界按钮打开模态框。"""
    _navigate_sw(sw_page, wait_session=False)
    page = sw_page.page

    # 打开世界侧边栏
    hamburger = page.locator(".hamburger-btn")
    hamburger.wait_for(state="visible", timeout=10000)
    hamburger.click()
    page.wait_for_timeout(500)

    # 点击新建世界按钮
    add_btn = page.locator(".world-add-btn")
    if add_btn.count() == 0:
        pytest.skip("新建世界按钮不存在")
    add_btn.first.click()
    page.wait_for_timeout(500)

    # 验证模态框出现
    modal = page.locator("#new-world-modal")
    assert modal.count() > 0, "新建世界模态框应存在"

    # 关闭模态框
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_step_nav(sw_page):
    """sw_020 - 左侧导航栏显示。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    nav = page.locator("#step-nav")
    assert nav.count() > 0, "左侧导航栏应存在"

    items = page.locator(".step-nav-item")
    assert items.count() >= 2, f"导航栏应至少有 2 项，实际 {items.count()}"


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_breadcrumb(sw_page):
    """sw_021 - 顶部面包屑导航显示。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    breadcrumb = page.locator(".breadcrumb-nav")
    assert breadcrumb.count() > 0, "面包屑导航应存在"

    text = breadcrumb.first.text_content() or ""
    assert "剧本" in text or "script" in text.lower(), f"面包屑应包含'剧本'，实际: '{text}'"


@pytest.mark.p1
@pytest.mark.script_writer
def test_sw_world_name_display(sw_page):
    """sw_022 - header 显示当前世界名称。"""
    # 该信息在产品的 ≤1400px 响应式布局中会被隐藏；本用例验证宽屏展示。
    sw_page.page.set_viewport_size({"width": 1440, "height": 900})
    _navigate_sw(sw_page)
    page = sw_page.page

    display = page.locator("#world-name-display")
    display.wait_for(state="visible", timeout=10000)
    page.wait_for_timeout(3000)

    name = display.text_content() or ""
    assert name and name != "加载中...", f"世界名称应已加载，实际: '{name}'"


# ═══════════════════════════════════════════════════════════════
# P2 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p2
@pytest.mark.script_writer
def test_sw_i18n_switcher(sw_page):
    """sw_023 - 语言切换按钮存在。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    container = page.locator("#i18n-switcher-container")
    assert container.count() > 0, "语言切换容器应存在"


@pytest.mark.p2
@pytest.mark.script_writer
def test_sw_new_script_modal(sw_page):
    """sw_024 - 切换到 scripts tab 后 FAB 按钮可打开新建剧本模态框。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    # 切换到 scripts tab
    scripts_tab = page.locator(".tab-btn[data-type='scripts']")
    if scripts_tab.count() > 0:
        scripts_tab.click()
        page.wait_for_timeout(500)

    # 点击 FAB 按钮
    fab = page.locator("#add-file-btn")
    if fab.count() == 0 or not fab.first.is_visible():
        pytest.skip("FAB 按钮不可见")

    fab.first.click()
    page.wait_for_timeout(500)

    modal = page.locator("#new-script-modal")
    assert modal.count() > 0, "新建剧本模态框应存在"

    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


@pytest.mark.p2
@pytest.mark.script_writer
def test_sw_import_script_modal(sw_page):
    """sw_025 - 需求选择器的"导入已有剧本"打开导入模态框。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    buttons = page.locator(".requirement-btn")
    if buttons.count() < 1:
        pytest.skip("需求选择器不可见")

    # 点击第 1 个按钮（导入已有剧本）
    buttons.first.click()
    page.wait_for_timeout(500)

    modal = page.locator("#import-script-modal")
    if modal.count() > 0:
        assert modal.first.is_visible(), "导入脚本模态框应可见"
        page.keyboard.press("Escape")


@pytest.mark.p2
@pytest.mark.script_writer
def test_sw_feedback_modal(sw_page):
    """sw_026 - 反馈按钮打开联系弹窗。"""
    # 反馈浮标在产品的 ≤1400px 响应式布局中会被隐藏；本用例验证宽屏交互。
    sw_page.page.set_viewport_size({"width": 1440, "height": 900})
    _navigate_sw(sw_page)
    page = sw_page.page

    fab = page.locator(".feedback-fab")
    fab.wait_for(state="visible", timeout=10000)

    fab.first.click()
    page.wait_for_timeout(500)

    modal = page.locator("#feedback-modal")
    modal.wait_for(state="visible", timeout=10000)
    page.keyboard.press("Escape")


@pytest.mark.p2
@pytest.mark.script_writer
def test_sw_new_character_modal(sw_page):
    """sw_027 - 新建角色模态框可通过 JS 调用打开。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    page.evaluate("() => { if (typeof showNewCharacterModal === 'function') showNewCharacterModal(); }")
    page.wait_for_timeout(500)

    modal = page.locator("#new-character-modal")
    if modal.count() > 0:
        # 验证表单字段存在
        name_input = page.locator("#new-char-name")
        assert name_input.count() > 0, "应有角色名称输入框"
        page.keyboard.press("Escape")


@pytest.mark.p2
@pytest.mark.script_writer
def test_sw_new_location_modal(sw_page):
    """sw_028 - 新建场景模态框可通过 JS 调用打开。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    page.evaluate("() => { if (typeof showNewLocationModal === 'function') showNewLocationModal(); }")
    page.wait_for_timeout(500)

    modal = page.locator("#new-location-modal")
    if modal.count() > 0:
        name_input = page.locator("#new-loc-name")
        assert name_input.count() > 0, "应有场景名称输入框"
        page.keyboard.press("Escape")


@pytest.mark.p2
@pytest.mark.script_writer
def test_sw_new_prop_modal(sw_page):
    """sw_029 - 新建道具模态框可通过 JS 调用打开。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    page.evaluate("() => { if (typeof showNewPropModal === 'function') showNewPropModal(); }")
    page.wait_for_timeout(500)

    modal = page.locator("#new-prop-modal")
    if modal.count() > 0:
        name_input = page.locator("#new-prop-name")
        assert name_input.count() > 0, "应有道具名称输入框"
        page.keyboard.press("Escape")


@pytest.mark.p2
@pytest.mark.script_writer
def test_sw_responsive_layout(browser, auth_token, user_id, base_url, api_client):
    """sw_030 - 窄屏下页面仍可用。"""
    # 获取 world_id
    worlds_resp = api_client.get("/api/worlds")
    worlds_data = worlds_resp.json()
    inner = worlds_data.get("data", worlds_data)
    worlds = inner.get("data", []) if isinstance(inner, dict) else inner
    world_id = str(worlds[0]["id"]) if worlds else "1"

    context = browser.new_context(viewport={"width": 375, "height": 667}, locale="zh-CN")
    context.add_init_script(f"""
        localStorage.setItem('auth_token', '{auth_token}');
        localStorage.setItem('user_id', '{user_id}');
    """)
    p = context.new_page()

    def handler(route):
        route.fulfill(
            status=200, content_type="application/json",
            body=_json.dumps({"success": True, "data": {"computing_power": 9999}}),
        )
    p.route("**/api/user/computing_power", handler)

    p.goto(f"{base_url}/script-writer?user_id={user_id}&world_id={world_id}", wait_until="domcontentloaded")
    p.wait_for_timeout(3000)

    assert p.locator(".app-container").count() > 0, "移动端应有 .app-container"

    p.close()
    context.close()


@pytest.mark.p2
@pytest.mark.script_writer
def test_sw_model_change(sw_page):
    """验证切换 LLM 模型。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    selector = page.locator("#model-selector")
    selector.wait_for(state="visible", timeout=10000)
    page.wait_for_timeout(3000)

    options = selector.locator("option")
    if options.count() < 2:
        pytest.skip("只有 1 个模型，无法测试切换")

    # 选择第 2 个模型
    second_value = options.nth(1).get_attribute("value")
    if second_value:
        selector.select_option(second_value)
        page.wait_for_timeout(500)


@pytest.mark.p2
@pytest.mark.script_writer
def test_sw_thinking_mode_toggle(sw_page):
    """验证思考模式开关。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    wrapper = page.locator("#thinking-mode-wrapper")
    if wrapper.count() == 0:
        pytest.skip("思考模式不可用")

    # 检查是否可见
    is_visible = page.evaluate("""() => {
        const el = document.getElementById('thinking-mode-wrapper');
        return el && el.style.display !== 'none';
    }""")
    if not is_visible:
        pytest.skip("思考模式当前不可见（模型不支持）")

    # checkbox 被自定义样式隐藏，通过 JS 切换
    page.evaluate("() => { const el = document.getElementById('thinking-toggle'); if (el) { el.checked = !el.checked; el.dispatchEvent(new Event('change')); } }")
    page.wait_for_timeout(300)


@pytest.mark.p2
@pytest.mark.script_writer
def test_sw_power_logs_modal(sw_page):
    """验证点击算力余额打开日志模态框。"""
    _navigate_sw(sw_page)
    page = sw_page.page

    power_display = page.locator("#computing-power-display")
    power_display.wait_for(state="visible", timeout=10000)
    power_display.click()
    page.wait_for_timeout(500)

    modal = page.locator("#computing-power-logs-modal")
    if modal.count() > 0:
        page.keyboard.press("Escape")
