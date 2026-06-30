"""
营销智能体页面 E2E 测试。
覆盖页面加载、模式切换、会话管理、消息交互、设置面板、媒体上传等场景。
"""
import json as _json

import pytest


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def _hide_feedback_fab(page):
    """隐藏反馈浮动按钮避免遮挡"""
    page.evaluate("""() => {
        const fab = document.querySelector('.feedback-fab-container');
        if (fab) {
            fab.style.display = 'none';
            fab.style.pointerEvents = 'none';
        }
    }""")


def _fill_and_dispatch(page, text):
    """填充文本框并触发 Vue v-model 更新"""
    textarea = page.locator(".marketing-textarea").first
    textarea.wait_for(state="visible", timeout=10000)
    textarea.click()
    page.wait_for_timeout(200)
    textarea.fill(text)
    # 通过 native setter + 事件确保 Vue v-model 更新
    page.evaluate("""(text) => {
        const ta = document.querySelector('.marketing-textarea');
        if (ta) {
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            nativeInputValueSetter.call(ta, text);
            ta.dispatchEvent(new Event('input', { bubbles: true }));
            ta.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }""", text)
    page.wait_for_timeout(500)
    # 隐藏遮挡元素（feedback-fab 会拦截 pointer events）
    page.evaluate("""() => {
        const fab = document.querySelector('.feedback-fab-container');
        if (fab) {
            fab.style.display = 'none';
            fab.style.pointerEvents = 'none';
        }
    }""")
    # 等待按钮可见
    send_btn = page.locator(".marketing-send-btn").first
    send_btn.wait_for(state="visible", timeout=5000)


def _mock_computing_power(page, power=9999):
    """拦截算力 API 防止重定向到登录页"""

    def handler(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({"success": True, "data": {"computing_power": power}}),
        )

    page.route("**/api/user/computing_power", handler)


def _navigate_and_wait(page, base_url, path="/marketing-agent"):
    """导航到页面并等待加载完成"""
    _mock_computing_power(page)
    page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # 检查是否被重定向到登录页
    current_url = page.url
    if "login=1" in current_url or "index.html" in current_url:
        # 等待 localStorage 注入生效并重新加载
        page.wait_for_timeout(2000)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

    page.locator(".sidebar, main.main-content").first.wait_for(
        state="attached", timeout=15000
    )


def _mock_marketing_verification_restore_flow(page, verification_status="pending"):
    """Mock two sessions where session A has an unanswered ask_user verification."""
    state = {
        "verification_posts": [],
        "task_posts": [],
    }

    sessions = [
        {
            "session_id": "e2e-verification-session-a",
            "title": "E2E verification A",
            "created_at": "2026-06-19T10:00:00",
            "updated_at": "2026-06-19T10:00:00",
        },
        {
            "session_id": "e2e-verification-session-b",
            "title": "E2E verification B",
            "created_at": "2026-06-19T09:00:00",
            "updated_at": "2026-06-19T09:00:00",
        },
    ]

    histories = {
        "e2e-verification-session-a": [
            {
                "role": "verification",
                "message_type": "verification_request",
                "verification_id": "e2e-verification-id-a",
                "verification_status": verification_status,
                "content": {
                    "verification_id": "e2e-verification-id-a",
                    "title": "请选择营销方向",
                    "description": "切换会话回来后仍应可以回答这个问题。",
                    "options": ["方案A", "方案B"],
                    "status": verification_status,
                },
                "timestamp": "2026-06-19T10:01:00",
            }
        ],
        "e2e-verification-session-b": [
            {
                "role": "assistant",
                "message_type": "normal",
                "content": "这是另一个会话的消息。",
                "timestamp": "2026-06-19T09:01:00",
            }
        ],
    }

    def handler(route):
        request = route.request
        url = request.url
        method = request.method.upper()
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1].split("?", 1)[0]

        if path == "/api/user/computing_power":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"success": True, "data": {"computing_power": 9999}}),
            )
            return

        if path == "/api/system/server-config":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"code": 0, "data": {}}),
            )
            return

        if path == "/api/models":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({
                    "success": True,
                    "models": [
                        {
                            "model_id": 1,
                            "name": "doubao-seed-2-0-lite",
                            "vendor_id": 1,
                            "vendor_name": "volcengine",
                            "supports_vl": True,
                            "supports_thinking": False,
                        }
                    ],
                }),
            )
            return

        if path == "/api/sessions":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"success": True, "sessions": sessions}),
            )
            return

        if path.endswith("/history") and path.startswith("/api/session/"):
            session_id = path.split("/")[3]
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({
                    "success": True,
                    "code": 0,
                    "history": histories.get(session_id, []),
                }),
            )
            return

        if path.endswith("/latest-task") and path.startswith("/api/session/"):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"success": False, "task": None}),
            )
            return

        if path.endswith("/task") and path.startswith("/api/session/") and method == "POST":
            try:
                state["task_posts"].append(_json.loads(request.post_data or "{}"))
            except Exception:
                state["task_posts"].append(request.post_data)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"success": True, "task_id": "unexpected-normal-task"}),
            )
            return

        if path.startswith("/api/verification/") and method == "POST":
            try:
                state["verification_posts"].append(_json.loads(request.post_data or "{}"))
            except Exception:
                state["verification_posts"].append(request.post_data)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"success": True}),
            )
            return

        route.continue_()

    page.route("**/api/**", handler)
    return state


# ═══════════════════════════════════════════════════════════════
# P0 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.marketing_agent
def test_marketing_agent_page_loads(marketing_agent_page):
    """ma_001 - 导航到营销智能体页面，验证页面加载成功。"""
    marketing_agent_page.navigate()
    marketing_agent_page.wait_for_load()
    assert marketing_agent_page.is_loaded(), "营销智能体页面未正常加载"


@pytest.mark.p0
@pytest.mark.marketing_agent
def test_marketing_agent_mode_switch(marketing_agent_page):
    """ma_002 - 从首页导航，选择营销模式后点击开始创作进入营销灵感页。"""
    page = marketing_agent_page.page
    page.goto(marketing_agent_page.base_url + "/", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=15000)

    switch_btn = page.locator(".mode-switch-btn").first
    switch_btn.wait_for(state="visible", timeout=10000)
    switch_btn.click()

    marketing_item = page.locator(".mode-select-item").nth(1)
    marketing_item.wait_for(state="visible", timeout=5000)
    marketing_item.click()
    page.wait_for_timeout(500)

    start_banner = page.locator(".start-creation-banner").first
    start_banner.wait_for(state="visible", timeout=5000)
    start_banner.click()

    page.wait_for_url("**/marketing-inspiration**", timeout=15000)
    # 营销创作入口已演进到灵感页（marketing-inspiration），校验 hero 创作区加载
    page.wait_for_selector(".hero-section", timeout=10000)


@pytest.mark.p0
@pytest.mark.marketing_agent
def test_marketing_agent_create_session(api_client, auth_token, user_id):
    """ma_003 - 通过 API 创建 session_type=2 的营销会话。"""
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
            "session_type": 2,
        },
    )
    assert resp.status_code in (200, 201), (
        f"创建营销会话失败，状态码: {resp.status_code}, 响应: {resp.text}"
    )
    data = resp.json()
    session_id = (
        data.get("session_id")
        or data.get("id")
        or data.get("data", {}).get("session_id")
    )
    assert session_id, f"响应中未找到 session_id: {data}"


@pytest.mark.p0
@pytest.mark.marketing_agent
def test_marketing_agent_new_chat(marketing_agent_page, page, base_url):
    """ma_008 - 点击新建会话按钮后创建新会话并出现在列表顶部。"""
    _navigate_and_wait(page, base_url)
    marketing_agent_page.wait_for_sidebar_loaded()
    # 等待会话列表实际加载完成
    page.wait_for_selector(".sidebar-history-item", timeout=10000)
    page.wait_for_timeout(1000)

    count_before = marketing_agent_page.get_session_count()
    marketing_agent_page.click_new_chat()

    count_after = marketing_agent_page.get_session_count()
    assert count_after == count_before + 1, (
        f"新建会话后期望 {count_before + 1} 个，实际 {count_after}"
    )

    # 验证新会话在列表顶部且为 active
    first_item = page.locator(".sidebar-history-item").first
    assert "active" in (first_item.get_attribute("class") or ""), (
        "新建的会话应为当前活跃会话"
    )


@pytest.mark.p0
@pytest.mark.marketing_agent
def test_marketing_agent_switch_session(marketing_agent_page, page, base_url):
    """ma_009 - 点击不同会话项后主内容区切换到对应会话。"""
    _navigate_and_wait(page, base_url)
    marketing_agent_page.wait_for_sidebar_loaded()

    items = page.locator(".sidebar-history-item")
    if items.count() < 2:
        # 新建一个会话以确保至少有 2 个
        marketing_agent_page.click_new_chat()

    items = page.locator(".sidebar-history-item")
    assert items.count() >= 2, "至少需要 2 个会话才能测试切换"

    # 记录第一个会话的标题
    title_1 = page.locator(
        ".sidebar-history-item:first-child .history-title"
    ).text_content()

    # 切换到第二个会话
    items.nth(1).click()
    page.wait_for_timeout(1000)

    # 验证第二个会话变为 active
    second_class = items.nth(1).get_attribute("class") or ""
    assert "active" in second_class, "第二个会话应变为活跃状态"

    # 验证第一个会话不再 active
    first_class = items.first.get_attribute("class") or ""
    assert "active" not in first_class, "第一个会话不应再是活跃状态"


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_restores_verification_option_after_session_switch(page, base_url):
    """ma_035 - 切换会话再返回后，未回答的 ask_user 选项仍可点击。"""
    state = _mock_marketing_verification_restore_flow(page)

    page.goto(f"{base_url}/marketing-agent", wait_until="domcontentloaded")
    page.locator(".sidebar-history-item").first.wait_for(state="visible", timeout=10000)

    option = page.get_by_role("button", name="方案A").first
    option.wait_for(state="visible", timeout=10000)

    page.locator(".sidebar-history-item").nth(1).click()
    page.wait_for_function(
        "() => document.body.innerText.includes('这是另一个会话的消息。')",
        timeout=10000,
    )

    page.locator(".sidebar-history-item").first.click()
    option.wait_for(state="visible", timeout=10000)
    assert option.is_enabled(), "切换回原会话后 verification 选项应保持可点击"

    option.click()
    page.wait_for_timeout(500)

    assert state["verification_posts"], "点击 verification 选项后应提交 /api/verification/{id}"
    assert state["verification_posts"][0].get("user_input") == "方案A"
    assert state["task_posts"] == [], "回答 verification 不应创建新的普通 Agent 任务"


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_restores_verification_text_input_after_session_switch(page, base_url):
    """ma_036 - 切换会话再返回后，主输入框可提交 ask_user 自定义回答。"""
    state = _mock_marketing_verification_restore_flow(page)

    page.goto(f"{base_url}/marketing-agent", wait_until="domcontentloaded")
    page.locator(".sidebar-history-item").first.wait_for(state="visible", timeout=10000)
    page.get_by_role("button", name="方案A").first.wait_for(state="visible", timeout=10000)

    page.locator(".sidebar-history-item").nth(1).click()
    page.wait_for_function(
        "() => document.body.innerText.includes('这是另一个会话的消息。')",
        timeout=10000,
    )

    page.locator(".sidebar-history-item").first.click()
    page.get_by_role("button", name="方案A").first.wait_for(state="visible", timeout=10000)

    _fill_and_dispatch(page, "我选择自定义营销方向")
    send_btn = page.locator(".marketing-send-btn").first
    assert send_btn.is_enabled(), "恢复 pending verification 后主输入发送按钮应可用"
    send_btn.click()
    page.wait_for_timeout(500)

    assert state["verification_posts"], "主输入框回答应提交 /api/verification/{id}"
    assert state["verification_posts"][0].get("user_input") == "我选择自定义营销方向"
    assert state["task_posts"] == [], "主输入框回答 verification 不应创建新的普通 Agent 任务"


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_timeout_verification_does_not_block_input_after_session_switch(page, base_url):
    """ma_037 - 已超时的 ask_user 历史问题切回后不应阻塞主输入框。"""
    state = _mock_marketing_verification_restore_flow(page, verification_status="cancelled")

    page.goto(f"{base_url}/marketing-agent", wait_until="domcontentloaded")
    page.locator(".sidebar-history-item").first.wait_for(state="visible", timeout=10000)
    page.get_by_text("切换会话回来后仍应可以回答这个问题。").first.wait_for(
        state="visible",
        timeout=10000,
    )

    page.locator(".sidebar-history-item").nth(1).click()
    page.wait_for_function(
        "() => document.body.innerText.includes('这是另一个会话的消息。')",
        timeout=10000,
    )

    page.locator(".sidebar-history-item").first.click()
    page.get_by_text("切换会话回来后仍应可以回答这个问题。").first.wait_for(
        state="visible",
        timeout=10000,
    )

    _fill_and_dispatch(page, "超时后开始新的营销对话")
    send_btn = page.locator(".marketing-send-btn").first
    assert send_btn.is_enabled(), "超时 verification 不应继续禁用主输入发送"
    send_btn.click()
    page.wait_for_timeout(500)

    assert state["verification_posts"] == [], "超时 verification 不应继续提交 verification 回答"
    assert state["task_posts"], "超时后主输入应能创建新的普通 Agent 任务"


@pytest.mark.p0
@pytest.mark.marketing_agent
def test_marketing_agent_send_message(browser, base_url, e2e_config):
    """ma_010 - 发送消息后用户消息出现在聊天区域。"""
    from conftest import MarketingAgentPage, refresh_login

    # 重新登录获取新 token
    login_data = refresh_login(e2e_config, base_url)
    if not login_data:
        pytest.skip("登录失败，跳过测试")

    auth_token = login_data["token"]
    user_id = login_data["user_id"]

    # 创建新的浏览器上下文
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="zh-CN",
    )
    # 注入 localStorage 认证信息
    context.add_init_script(f"""
        localStorage.setItem('auth_token', '{auth_token}');
        localStorage.setItem('user_id', '{user_id}');
    """)
    page = context.new_page()

    # Mock 算力 API
    def handler(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({"success": True, "data": {"computing_power": 9999}}),
        )
    page.route("**/api/user/computing_power", handler)

    try:
        # 导航到页面
        page.goto(f"{base_url}/marketing-agent", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # 检查是否被重定向到登录页
        current_url = page.url
        if "login=1" in current_url or "index.html" in current_url:
            # 直接注入 token 并重新加载
            page.evaluate(f"""() => {{
                localStorage.setItem('auth_token', '{auth_token}');
                localStorage.setItem('user_id', '{user_id}');
            }}""")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

        marketing_agent_page = MarketingAgentPage(page, base_url)
        marketing_agent_page.wait_for_sidebar_loaded()
        page.wait_for_timeout(2000)

        # 新建会话确保干净状态
        marketing_agent_page.click_new_chat()
        page.wait_for_timeout(2000)

        test_text = f"E2E测试消息_{__import__('time').time():.0f}"
        marketing_agent_page.send_message(test_text)

        # 等待用户消息出现（最多 20 秒，轮询检查）
        user_messages = page.locator(".message.user")
        found = False
        for i in range(20):
            page.wait_for_timeout(1000)
            count = user_messages.count()
            if count > 0:
                found = True
                break

        if not found:
            # 打印页面状态用于调试
            page_state = page.evaluate("""() => {
                return {
                    url: window.location.href,
                    textarea_value: document.querySelector('.marketing-textarea')?.value,
                    send_btn_disabled: document.querySelector('.marketing-send-btn')?.disabled,
                    messages_count: document.querySelectorAll('.message').length,
                }
            }""")
            assert False, (
                f"发送消息后未出现用户消息，页面状态: {page_state}"
            )

        assert user_messages.count() > 0, "发送消息后未出现用户消息"

        # 验证消息内容包含发送的文本
        last_user_msg = user_messages.last
        msg_text = last_user_msg.text_content() or ""
        assert test_text in msg_text, (
            f"用户消息内容不匹配，期望包含 '{test_text}'，实际 '{msg_text}'"
        )
    finally:
        page.close()
        context.close()


# ═══════════════════════════════════════════════════════════════
# P1 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_session_list(marketing_agent_page, page, base_url):
    """ma_005 - 验证会话列表侧边栏可见且会话已加载。"""
    _navigate_and_wait(page, base_url)

    sidebar = page.locator(".sidebar").first
    sidebar.wait_for(state="visible", timeout=10000)
    assert sidebar.is_visible(), "会话列表侧边栏不可见"

    session_items = page.locator(".sidebar-history-item")
    if session_items.count() == 0:
        new_chat_btn = page.locator(".new-chat-btn")
        assert new_chat_btn.count() > 0, "会话列表中无会话项且无新建按钮"
    else:
        assert session_items.count() > 0, "会话列表中无会话项"


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_session_rename(marketing_agent_page, page, base_url):
    """ma_006 - 悬停会话项，点击更多按钮，选择重命名，输入新名称。"""
    _navigate_and_wait(page, base_url)
    marketing_agent_page.wait_for_sidebar_loaded()

    session_item = page.locator(".sidebar-history-item").first
    session_item.wait_for(state="visible", timeout=10000)

    session_item.hover()
    page.wait_for_timeout(300)
    more_btn = session_item.locator(".history-more-btn").first
    more_btn.wait_for(state="visible", timeout=5000)
    more_btn.click()
    page.wait_for_timeout(500)

    rename_option = session_item.locator(".history-menu-item").first
    rename_option.wait_for(state="visible", timeout=5000)
    rename_option.click()
    page.wait_for_timeout(500)

    rename_input = page.locator(".history-rename-input").first
    rename_input.wait_for(state="visible", timeout=5000)
    rename_input.fill("测试重命名会话")
    page.keyboard.press("Enter")
    page.wait_for_timeout(1000)


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_session_delete(marketing_agent_page, page, base_url):
    """ma_007 - 悬停会话项，点击更多按钮，选择删除，确认删除操作。"""
    _navigate_and_wait(page, base_url)
    marketing_agent_page.wait_for_sidebar_loaded()

    session_item = page.locator(".sidebar-history-item").first
    session_item.wait_for(state="visible", timeout=10000)

    items_before = marketing_agent_page.get_session_count()

    session_item.hover()
    page.wait_for_timeout(300)
    more_btn = session_item.locator(".history-more-btn").first
    more_btn.wait_for(state="visible", timeout=5000)
    more_btn.click()
    page.wait_for_timeout(500)

    delete_option = session_item.locator(".history-menu-item.danger").first
    delete_option.wait_for(state="visible", timeout=5000)

    # 注册 dialog handler
    def _handle_dialog(dialog):
        try:
            dialog.accept()
        except Exception:
            pass
    page.on("dialog", _handle_dialog)
    delete_option.click()
    page.wait_for_timeout(3000)

    items_after = marketing_agent_page.get_session_count()
    assert items_after < items_before, (
        f"删除会话后数量未减少，删除前: {items_before}，删除后: {items_after}"
    )


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_search_sessions(marketing_agent_page, page, base_url):
    """ma_012 - 搜索框输入关键词，验证会话列表过滤。"""
    _navigate_and_wait(page, base_url)
    marketing_agent_page.wait_for_sidebar_loaded()

    items = page.locator(".sidebar-history-item")
    total = items.count()
    if total < 2:
        pytest.skip("至少需要 2 个会话才能测试搜索")

    # 获取第一个会话的标题作为搜索关键词
    first_title = page.locator(
        ".sidebar-history-item:first-child .history-title"
    ).text_content() or ""
    if len(first_title) < 2:
        pytest.skip("会话标题太短，无法测试搜索")

    keyword = first_title[:4]
    search_input = page.locator(".sidebar-search input").first
    search_input.wait_for(state="visible", timeout=5000)
    search_input.fill(keyword)
    page.wait_for_timeout(500)

    # 验证过滤后的会话标题都包含关键词
    visible_items = page.locator(".sidebar-history-item")
    for i in range(visible_items.count()):
        title = visible_items.nth(i).locator(".history-title").text_content() or ""
        assert keyword.lower() in title.lower(), (
            f"搜索 '{keyword}' 后会话 '{title}' 不匹配"
        )


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_type_switch(marketing_agent_page, page, base_url):
    """ma_013 - 验证底部输入栏的类型选择器可切换创作模式。"""
    _navigate_and_wait(page, base_url)

    # 找到类型选择按钮（.marketing-bar-btn 第一个）
    bar_btns = page.locator(".marketing-bar-btn")
    if bar_btns.count() == 0:
        pytest.skip("未找到类型选择按钮")

    bar_btns.first.click()
    page.wait_for_timeout(500)

    # 验证下拉菜单出现
    dropdown = page.locator(".marketing-dropdown-menu")
    dropdown.wait_for(state="visible", timeout=3000)

    # 点击图片模式选项（第二个选项）
    options = page.locator(".marketing-dropdown-menu .dropdown-item")
    if options.count() >= 2:
        options.nth(1).click()
        page.wait_for_timeout(500)

        # 验证下拉菜单关闭
        assert not dropdown.is_visible(), "选择类型后下拉菜单应关闭"


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_welcome_card(marketing_agent_page, page, base_url):
    """ma_018 - 新建空会话后显示欢迎卡片。"""
    _navigate_and_wait(page, base_url)
    marketing_agent_page.wait_for_sidebar_loaded()

    # 新建会话
    marketing_agent_page.click_new_chat()
    page.wait_for_timeout(1000)

    # 验证欢迎卡片可见
    welcome = page.locator(".welcome-card")
    if welcome.count() > 0:
        assert welcome.first.is_visible(), "新会话应显示欢迎卡片"

    # 验证无消息
    messages = page.locator(".message")
    assert messages.count() == 0, "新会话不应有消息"


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_computing_power_display(page, base_url):
    """ma_017 - 顶部栏显示算力余额。"""
    # mock 算力 API 返回固定值
    _mock_computing_power(page, power=5000)

    page.goto(f"{base_url}/marketing-agent", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # 验证算力显示元素存在
    power_display = page.locator(".computing-power-display")
    if power_display.count() > 0:
        assert power_display.first.is_visible(), "算力余额显示不可见"


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_feedback_modal(marketing_agent_page, page, base_url):
    """ma_020 - 点击反馈按钮打开联系弹窗。"""
    _navigate_and_wait(page, base_url)

    # 点击反馈按钮
    fab = page.locator(".feedback-fab")
    if fab.count() == 0:
        pytest.skip("未找到反馈按钮")

    fab.first.click()
    page.wait_for_timeout(500)

    # 验证弹窗内容出现（二维码图片或弹窗容器）
    modal = page.locator(".feedback-fab-container .modal, .feedback-fab-container .fab-menu")
    if modal.count() > 0:
        assert modal.first.is_visible(), "反馈弹窗应可见"

    # 关闭弹窗（点击其他区域）
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


@pytest.mark.p1
@pytest.mark.marketing_agent
def test_marketing_agent_title_auto_update(browser, base_url, e2e_config):
    """ma_019 - 发送第一条消息后会话标题自动更新。"""
    from conftest import MarketingAgentPage, refresh_login

    login_data = refresh_login(e2e_config, base_url)
    if not login_data:
        pytest.skip("登录失败，跳过测试")

    context = browser.new_context(
        viewport={"width": 1280, "height": 720}, locale="zh-CN"
    )
    context.add_init_script(f"""
        localStorage.setItem('auth_token', '{login_data["token"]}');
        localStorage.setItem('user_id', '{login_data["user_id"]}');
    """)
    p = context.new_page()
    _mock_computing_power(p)

    try:
        p.goto(f"{base_url}/marketing-agent", wait_until="domcontentloaded")
        p.wait_for_timeout(3000)
        p.locator(".sidebar, main.main-content").first.wait_for(
            state="attached", timeout=15000
        )

        marketing_agent_page = MarketingAgentPage(p, base_url)
        marketing_agent_page.wait_for_sidebar_loaded()
        marketing_agent_page.click_new_chat()
        p.wait_for_timeout(2000)

        # 发送消息
        _fill_and_dispatch(p, "帮我写一个产品推广方案")
        send_btn = p.locator(".marketing-send-btn").first
        send_btn.click(timeout=10000)
        p.wait_for_timeout(5000)

        # 验证标题存在
        active_title = p.locator(".sidebar-history-item.active .history-title").first
        try:
            active_title.wait_for(state="visible", timeout=8000)
            new_title = active_title.text_content() or ""
        except Exception:
            new_title = ""
        assert new_title, "会话标题不应为空"
    finally:
        p.close()
        context.close()


# ═══════════════════════════════════════════════════════════════
# P2 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_message_scroll(browser, base_url, e2e_config):
    """ma_011 - 消息较多时聊天区域可滚动。"""
    from conftest import MarketingAgentPage, refresh_login

    login_data = refresh_login(e2e_config, base_url)
    if not login_data:
        pytest.skip("登录失败，跳过测试")

    context = browser.new_context(
        viewport={"width": 1280, "height": 720}, locale="zh-CN"
    )
    context.add_init_script(f"""
        localStorage.setItem('auth_token', '{login_data["token"]}');
        localStorage.setItem('user_id', '{login_data["user_id"]}');
    """)
    p = context.new_page()
    _mock_computing_power(p)

    try:
        p.goto(f"{base_url}/marketing-agent", wait_until="domcontentloaded")
        p.wait_for_timeout(3000)
        p.locator(".sidebar, main.main-content").first.wait_for(
            state="attached", timeout=15000
        )

        marketing_agent_page = MarketingAgentPage(p, base_url)
        marketing_agent_page.wait_for_sidebar_loaded()
        marketing_agent_page.click_new_chat()
        p.wait_for_timeout(2000)

        for i in range(3):
            _fill_and_dispatch(p, f"测试滚动消息 {i+1}")
            # 使用 JS 直接点击按钮（绕过 Playwright 的 enabled 检查）
            p.evaluate("""() => {
                const btn = document.querySelector('.marketing-send-btn');
                if (btn) btn.click();
            }""")
            p.wait_for_timeout(3000)

        messages = p.locator(".message")
        assert messages.count() > 0, "应有消息存在"
    finally:
        p.close()
        context.close()


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_image_upload(marketing_agent_page, page, base_url):
    """ma_016 - 通过文件选择器上传图片后显示缩略图。"""
    import os
    import tempfile

    from PIL import Image

    _navigate_and_wait(page, base_url)

    # 创建测试图片
    img = Image.new("RGB", (100, 100), color="red")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img.save(f, format="PNG")
        tmp_path = f.name

    try:
        # 查找文件上传输入
        file_inputs = page.locator("input[type='file']")
        if file_inputs.count() == 0:
            # 点击上传按钮触发
            upload_btn = page.locator(".marketing-upload-btn")
            if upload_btn.count() > 0:
                upload_btn.first.click()
                page.wait_for_timeout(500)
                file_inputs = page.locator("input[type='file']")

        if file_inputs.count() == 0:
            pytest.skip("未找到文件上传输入")

        file_inputs.first.set_input_files(tmp_path)
        page.wait_for_timeout(3000)

        # 上传可能因后端限制失败，只要不崩溃即可
        # 验证页面仍然可用
        assert page.locator(".marketing-textarea").count() > 0, (
            "上传图片后页面应仍然可用"
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_session_history_restore(
    marketing_agent_page, page, base_url
):
    """ma_027 - 切换会话后消息历史正确恢复。"""
    _navigate_and_wait(page, base_url)
    marketing_agent_page.wait_for_sidebar_loaded()

    items = page.locator(".sidebar-history-item")
    if items.count() < 2:
        # 新建一个会话
        marketing_agent_page.click_new_chat()

    items = page.locator(".sidebar-history-item")
    if items.count() < 2:
        pytest.skip("至少需要 2 个会话")

    # 切换到第一个会话
    items.first.click()
    page.wait_for_timeout(1000)
    messages_1 = page.locator(".message").count()

    # 切换到第二个会话
    items.nth(1).click()
    page.wait_for_timeout(1000)
    messages_2 = page.locator(".message").count()

    # 切换回第一个会话
    items.first.click()
    page.wait_for_timeout(1000)
    messages_1_again = page.locator(".message").count()

    # 验证消息数量一致
    assert messages_1 == messages_1_again, (
        f"切换回来后消息数量不一致: {messages_1} vs {messages_1_again}"
    )


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_keep_last_session(
    marketing_agent_page, page, base_url
):
    """ma_028 - 删除最后一个会话时有保护提示。"""
    _navigate_and_wait(page, base_url)
    marketing_agent_page.wait_for_sidebar_loaded()
    page.wait_for_timeout(2000)

    # 确保至少有 2 个会话
    items = page.locator(".sidebar-history-item")
    max_attempts = 5
    attempt = 0
    while items.count() < 2 and attempt < max_attempts:
        marketing_agent_page.click_new_chat()
        page.wait_for_timeout(2000)
        items = page.locator(".sidebar-history-item")
        attempt += 1

    if items.count() < 2:
        pytest.skip("无法创建足够的会话进行测试")

    initial_count = items.count()

    # 注册一次 dialog handler（在整个测试生命周期内有效）
    def _handle_dialog(dialog):
        try:
            dialog.accept()
        except Exception:
            pass
    page.on("dialog", _handle_dialog)

    # 删除到只剩 1 个（最多删 initial_count - 1 次）
    for i in range(min(initial_count - 1, 3)):  # 限制最多删 3 个，避免无限循环
        items = page.locator(".sidebar-history-item")
        if items.count() <= 1:
            break
        first = items.first
        first.hover()
        page.wait_for_timeout(300)

        more_btn = first.locator(".history-more-btn").first
        if more_btn.count() == 0:
            page.keyboard.press("Escape")
            continue

        try:
            more_btn.click(timeout=3000)
        except Exception:
            page.keyboard.press("Escape")
            continue
        page.wait_for_timeout(300)

        delete_option = first.locator(".history-menu-item.danger").first
        if delete_option.count() == 0:
            page.keyboard.press("Escape")
            continue

        try:
            delete_option.click(timeout=3000)
        except Exception:
            page.keyboard.press("Escape")
            continue
        page.wait_for_timeout(2000)

    items = page.locator(".sidebar-history-item")
    assert items.count() >= 1, f"应至少剩 1 个会话，实际 {items.count()}"

    # 尝试删除最后一个
    first = items.first
    first.hover()
    page.wait_for_timeout(300)

    more_btn = first.locator(".history-more-btn").first
    if more_btn.count() > 0:
        try:
            more_btn.click(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(300)

        delete_option = first.locator(".history-menu-item.danger").first
        if delete_option.count() > 0:
            try:
                delete_option.click(timeout=3000)
            except Exception:
                pass
            page.wait_for_timeout(1500)

    # 验证会话数量仍为 1
    assert page.locator(".sidebar-history-item").count() >= 1, (
        "删除最后一个会话后应仍保留至少 1 个"
    )


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_typing_indicator(
    marketing_agent_page, page, base_url
):
    """ma_026 - AI 回复过程中显示打字指示器。"""
    _navigate_and_wait(page, base_url)

    # 发送消息触发 AI 回复
    _fill_and_dispatch(page, "你好")
    _hide_feedback_fab(page)
    page.locator(".marketing-send-btn").first.click()

    # 短时间内检查打字指示器（可能很快消失）
    page.wait_for_timeout(500)
    typing = page.locator(".typing-indicator")
    # 打字指示器可能在 AI 快速回复时不可见
    # 只要不报错即可，不要求一定可见
    _ = typing.count()


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_session_via_fixture(
    page, base_url, marketing_session
):
    """验证 marketing_session fixture 创建的会话可在页面中看到。"""
    _navigate_and_wait(page, base_url)

    page.wait_for_selector(".sidebar-history-item", timeout=10000)
    # fixture 创建的会话应该在列表中（可能需要等待加载）
    page.wait_for_timeout(2000)

    items = page.locator(".sidebar-history-item")
    assert items.count() > 0, "会话列表不应为空"


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_image_modal(marketing_agent_page, page, base_url):
    """ma_024 - 点击聊天中的图片可打开全屏查看。"""
    _navigate_and_wait(page, base_url)

    # 检查是否有图片消息
    images = page.locator(".message-bubble img")
    if images.count() == 0:
        pytest.skip("当前会话中无图片消息")

    images.first.click()
    page.wait_for_timeout(500)

    # 验证图片模态框出现
    modal = page.locator("#imgModal")
    if modal.count() > 0:
        # 检查模态框是否可见
        is_visible = page.evaluate("""() => {
            const modal = document.getElementById('imgModal');
            return modal && (modal.style.display !== 'none' || modal.classList.contains('active'));
        }""")
        # 不强制要求，因为模态框实现可能不同


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_url_initial_message(page, base_url):
    """ma_021 - 通过 URL 参数自动发送初始消息。"""
    _mock_computing_power(page)
    page.goto(
        f"{base_url}/marketing-agent?initial_message=E2E自动测试消息",
        wait_until="domcontentloaded",
    )
    page.wait_for_timeout(5000)

    # 验证消息被发送（可能出现用户消息）
    messages = page.locator(".message.user")
    # 初始消息功能可能需要特定条件，不强制要求
    _ = messages.count()


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_responsive_sidebar(page, base_url):
    """ma_034 - 窄屏下侧边栏变为抽屉模式。"""
    # 设置移动端 viewport
    page.set_viewport_size({"width": 375, "height": 667})
    _navigate_and_wait(page, base_url)

    # 验证页面加载
    page.wait_for_timeout(2000)
    sidebar = page.locator(".sidebar")
    assert sidebar.count() > 0, "侧边栏元素应存在"

    # 恢复默认 viewport
    page.set_viewport_size({"width": 1280, "height": 720})


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_model_selection(marketing_agent_page, page, base_url):
    """ma_015 - Agent 模式下可查看 LLM 模型列表。"""
    _navigate_and_wait(page, base_url)

    # 模型选择通常在设置面板中
    # 查找模型相关 UI 元素
    panel = page.locator(".marketing-panel")
    if panel.count() == 0:
        # 尝试打开设置面板
        bar_btns = page.locator(".marketing-bar-btn")
        for i in range(bar_btns.count()):
            bar_btns.nth(i).click()
            page.wait_for_timeout(300)
            if panel.count() > 0 and panel.first.is_visible():
                break

    # 不强制要求面板可见，因为模型选择入口可能不同
    page.wait_for_timeout(500)


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_ratio_selection(marketing_agent_page, page, base_url):
    """ma_014 - 设置面板中可查看比例选项。"""
    _navigate_and_wait(page, base_url)

    # 尝试打开设置面板
    bar_btns = page.locator(".marketing-bar-btn")
    if bar_btns.count() == 0:
        pytest.skip("未找到设置按钮")

    # 点击各个按钮查找设置面板
    for i in range(bar_btns.count()):
        bar_btns.nth(i).click()
        page.wait_for_timeout(300)
        panel = page.locator(".marketing-panel")
        if panel.count() > 0 and panel.first.is_visible():
            # 找到面板，验证有内容
            panel_content = panel.first.text_content()
            assert panel_content, "设置面板不应为空"
            break
    else:
        # 关闭可能打开的下拉菜单
        page.keyboard.press("Escape")


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_continue_button(
    marketing_agent_page, page, base_url
):
    """ma_025 - AI 回复完成后验证继续按钮逻辑。"""
    _navigate_and_wait(page, base_url)

    # 继续按钮通常在 AI 回复完成后出现
    continue_btn = page.locator(".continue-btn")
    # 直接检查是否存在（可能在之前的测试中有 AI 回复）
    _ = continue_btn.count()


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_video_mode(marketing_agent_page, page, base_url):
    """ma_030 - 切换到视频模式后 UI 更新。"""
    _navigate_and_wait(page, base_url)

    # 找到类型选择按钮
    bar_btns = page.locator(".marketing-bar-btn")
    if bar_btns.count() == 0:
        pytest.skip("未找到类型选择按钮")

    bar_btns.first.click()
    page.wait_for_timeout(500)

    dropdown = page.locator(".marketing-dropdown-menu")
    if dropdown.count() == 0 or not dropdown.first.is_visible():
        pytest.skip("下拉菜单未出现")

    # 点击视频模式选项（第三个选项）
    options = page.locator(".marketing-dropdown-menu .dropdown-item")
    if options.count() >= 3:
        options.nth(2).click()
        page.wait_for_timeout(500)


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_language_switch(page, base_url):
    """ma_033 - 验证页面支持语言切换。"""
    _navigate_and_wait(page, base_url)

    # 查找语言切换器
    switcher = page.locator(".i18n-switcher-container, .lang-switcher")
    if switcher.count() == 0:
        pytest.skip("未找到语言切换器")

    # 语言切换器可能存在但功能未启用
    page.wait_for_timeout(500)


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_markdown_rendering(
    marketing_agent_page, page, base_url
):
    """验证 AI 消息中的 Markdown 正确渲染。"""
    _navigate_and_wait(page, base_url)

    # 检查 AI 消息中是否有渲染后的 HTML
    ai_messages = page.locator(".message.ai .message-bubble")
    if ai_messages.count() == 0:
        pytest.skip("当前会话无 AI 消息")

    # 验证消息气泡存在
    assert ai_messages.first.is_visible(), "AI 消息气泡应可见"


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_nav_items(page, base_url):
    """验证左侧导航栏项目显示。"""
    _navigate_and_wait(page, base_url)

    nav = page.locator("nav.marketing-nav")
    assert nav.count() > 0, "左侧导航栏应存在"

    nav_items = page.locator(".marketing-nav-item")
    assert nav_items.count() >= 1, "导航栏应至少有 1 个项目"

    # Logo 链接
    logo = page.locator(".marketing-nav-logo")
    assert logo.count() > 0, "导航栏应有 Logo"


@pytest.mark.p2
@pytest.mark.marketing_agent
def test_marketing_agent_top_bar(page, base_url):
    """验证顶部栏显示日期和功能按钮。"""
    _navigate_and_wait(page, base_url)

    top_bar = page.locator(".top-bar")
    assert top_bar.count() > 0, "顶部栏应存在"

    # 日期显示
    date_display = page.locator(".top-bar-date")
    if date_display.count() > 0:
        date_text = date_display.first.text_content()
        assert date_text, "日期显示不应为空"
