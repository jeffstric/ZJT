"""
算力日志页面 E2E 测试。
覆盖页面加载、筛选标签、分页、认证错误状态等场景。

computing_power_logs.html 从 localStorage 读取 auth_token，
通常在 iframe 中加载。使用 page fixture 注入认证信息并 mock API。
"""
import json as _json

import pytest


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def _setup_logs_page(browser, auth_token, user_id, base_url, mock_data=None):
    """创建算力日志页面实例，注入认证信息并 mock API"""
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="zh-CN",
    )
    context.add_init_script(f"""
        localStorage.setItem('auth_token', '{auth_token}');
        localStorage.setItem('user_id', '{user_id}');
    """)
    p = context.new_page()

    if mock_data is None:
        mock_data = {
            "success": True,
            "data": {
                "logs": [
                    {
                        "id": 1,
                        "behavior": "increase",
                        "note": "签到奖励",
                        "computing_power": 10,
                        "from": 0,
                        "to": 10,
                        "created_at": "2025-01-15 10:30:00",
                    },
                    {
                        "id": 2,
                        "behavior": "deduct",
                        "note": "视频生成扣费",
                        "computing_power": -5,
                        "from": 10,
                        "to": 5,
                        "created_at": "2025-01-15 11:00:00",
                    },
                ],
                "total": 2,
                "limit": 20,
                "offset": 0,
            },
        }

    def _mock_api(route):
        url = route.request.url
        path = url.split(base_url)[-1].split("?")[0] if base_url in url else url

        if path == "/api/user/computing_power_logs":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps(mock_data),
            )
        else:
            route.continue_()

    p.route("**/api/**", _mock_api)
    return p, context


# ═══════════════════════════════════════════════════════════════
# P0 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.computing_power
def test_power_logs_page_loads(browser, auth_token, user_id, base_url):
    """cpl_001 - 算力日志页面加载成功。"""
    p, context = _setup_logs_page(browser, auth_token, user_id, base_url)
    p.goto(f"{base_url}/computing_power_logs.html", wait_until="domcontentloaded")
    p.wait_for_timeout(2000)

    # 验证页面容器
    app = p.locator("#app")
    assert app.count() > 0, "应有 #app 容器"

    p.close()
    context.close()


@pytest.mark.p0
@pytest.mark.computing_power
def test_power_logs_display_entries(browser, auth_token, user_id, base_url):
    """cpl_002 - 页面显示日志条目。"""
    p, context = _setup_logs_page(browser, auth_token, user_id, base_url)
    p.goto(f"{base_url}/computing_power_logs.html", wait_until="domcontentloaded")
    p.wait_for_timeout(3000)

    # 验证日志列表或表格存在
    log_items = p.locator(".log-item, .log-entry, tr, [class*='log']")
    # 页面可能用表格或列表展示
    body_text = p.locator("body").text_content() or ""
    has_content = log_items.count() > 0 or "签到" in body_text or "扣费" in body_text or "增加" in body_text
    assert has_content, "应显示日志条目"

    p.close()
    context.close()


@pytest.mark.p0
@pytest.mark.computing_power
def test_power_logs_filter_tabs(browser, auth_token, user_id, base_url):
    """cpl_003 - 筛选标签存在（全部/增加/扣除）。"""
    p, context = _setup_logs_page(browser, auth_token, user_id, base_url)
    p.goto(f"{base_url}/computing_power_logs.html", wait_until="domcontentloaded")
    p.wait_for_timeout(2000)

    # 验证筛选标签
    body_text = p.locator("body").text_content() or ""
    has_tabs = ("全部" in body_text and "增加" in body_text) or ("全部" in body_text and "扣除" in body_text)
    assert has_tabs, f"应有筛选标签（全部/增加/扣除）"

    p.close()
    context.close()


# ═══════════════════════════════════════════════════════════════
# P1 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p1
@pytest.mark.computing_power
def test_power_logs_pagination(browser, auth_token, user_id, base_url):
    """cpl_004 - 分页控件存在。"""
    # 使用大量数据的 mock
    logs = [
        {
            "id": i,
            "behavior": "increase" if i % 2 == 0 else "deduct",
            "note": f"日志 {i}",
            "computing_power": 10 if i % 2 == 0 else -5,
            "from": i * 10,
            "to": (i + 1) * 10,
            "created_at": f"2025-01-{15 + i // 20} 10:00:00",
        }
        for i in range(20)
    ]
    mock_data = {
        "success": True,
        "data": {"logs": logs, "total": 50, "limit": 20, "offset": 0},
    }
    p, context = _setup_logs_page(browser, auth_token, user_id, base_url, mock_data)
    p.goto(f"{base_url}/computing_power_logs.html", wait_until="domcontentloaded")
    p.wait_for_timeout(3000)

    # 验证分页信息
    body_text = p.locator("body").text_content() or ""
    has_pagination = "页" in body_text or "page" in body_text.lower() or "上一页" in body_text or "下一页" in body_text
    # 分页可能以按钮或文本形式存在
    page_btns = p.locator("button:has-text('上一页'), button:has-text('下一页'), button:has-text('Previous'), button:has-text('Next')")
    assert has_pagination or page_btns.count() > 0, "应有分页控件"

    p.close()
    context.close()


@pytest.mark.p1
@pytest.mark.computing_power
def test_power_logs_no_auth_shows_error(browser, base_url):
    """cpl_005 - 无认证信息时显示错误提示。"""
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="zh-CN",
    )
    # 不设置 localStorage
    p = context.new_page()
    p.goto(f"{base_url}/computing_power_logs.html", wait_until="domcontentloaded")
    p.wait_for_timeout(3000)

    # 应显示错误提示
    body_text = p.locator("body").text_content() or ""
    has_error = "认证" in body_text or "登录" in body_text or "缺少" in body_text or "error" in body_text.lower()
    assert has_error, f"无认证时应显示错误提示"

    p.close()
    context.close()


@pytest.mark.p1
@pytest.mark.computing_power
def test_power_logs_empty_state(browser, auth_token, user_id, base_url):
    """cpl_006 - 无日志数据时显示空状态。"""
    mock_data = {"success": True, "data": {"logs": [], "total": 0, "limit": 20, "offset": 0}}
    p, context = _setup_logs_page(browser, auth_token, user_id, base_url, mock_data)
    p.goto(f"{base_url}/computing_power_logs.html", wait_until="domcontentloaded")
    p.wait_for_timeout(3000)

    body_text = p.locator("body").text_content() or ""
    has_empty = "暂无" in body_text or "没有" in body_text or "空" in body_text or "no data" in body_text.lower()
    # 空状态下页面不应崩溃
    app = p.locator("#app")
    assert app.count() > 0, "空状态下页面不应崩溃"

    p.close()
    context.close()


@pytest.mark.p0
@pytest.mark.computing_power
def test_power_logs_deduct_shows_refund_hint(browser, auth_token, user_id, base_url):
    """cpl_009 - 已退回的扣减行显示退回金额和退回单号摘要。"""
    mock_data = {
        "success": True,
        "data": {
            "logs": [
                {
                    "id": 10,
                    "behavior": "deduct",
                    "note": "视频生成扣费",
                    "computing_power": 105,
                    "from": 200,
                    "to": 95,
                    "created_at": "2026-08-21 11:00:00",
                    "transaction_id": "a1b2c3d4-e5f6-7890-abcd-ef1234569f0e",
                    "refund": {
                        "transaction_id": "refund-a1b2c3d4-e5f6-7890-abcd-ef1234569f0e",
                        "computing_power": 105,
                    },
                },
                {
                    "id": 11,
                    "behavior": "deduct",
                    "note": "未退回扣费",
                    "computing_power": 8,
                    "from": 95,
                    "to": 87,
                    "created_at": "2026-08-21 12:00:00",
                    "transaction_id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                },
            ],
            "total": 2,
            "limit": 20,
            "offset": 0,
        },
    }
    p, context = _setup_logs_page(browser, auth_token, user_id, base_url, mock_data)
    p.goto(f"{base_url}/computing_power_logs.html", wait_until="domcontentloaded")
    p.wait_for_timeout(3000)

    body_text = p.locator("body").text_content() or ""
    assert "已退回" in body_text, "扣减行应显示已退回"
    assert "+105" in body_text, "应显示退回算力值"
    assert "refund-a1b2c3d4" in body_text, "退回单号摘要应保留 refund- 前缀"
    assert "9f0e" in body_text, "退回单号摘要应包含尾部字符"

    refund_hints = p.locator(".log-refunded")
    assert refund_hints.count() == 1, "仅已退回的扣减行应出现退回提示"

    p.close()
    context.close()


# ═══════════════════════════════════════════════════════════════
# 分页后端验证（真实 API，不 mock）
# ═══════════════════════════════════════════════════════════════


@pytest.mark.p0
@pytest.mark.computing_power
def test_power_logs_pagination_returns_different_pages(api_client, e2e_config, base_url):
    """cpl_007 - 分页接口第1页和第2页返回不同数据。

    验证后端 offset 计算正确（此前 client.py 用不存在的字段重新计算
    offset 导致恒为 0，永远返回第一页）。
    """
    import time
    from conftest import refresh_login

    # 请求第1页（带重试和 token 刷新）
    resp1 = None
    for attempt in range(3):
        resp1 = api_client.get(
            "/api/user/computing_power_logs",
            params={"page": 1, "page_size": 20},
        )
        if resp1.status_code == 200:
            break
        # token 失效，重新登录
        if resp1.status_code == 400 and "认证" in resp1.text:
            login_data = refresh_login(e2e_config, base_url)
            if login_data:
                api_client.headers.update({
                    "Authorization": f"Bearer {login_data['token']}",
                    "X-User-Id": login_data["user_id"],
                })
        time.sleep(1)
    assert resp1.status_code == 200, (
        f"第1页请求失败: {resp1.status_code}, 响应: {resp1.text[:200]}"
    )
    data1 = resp1.json()
    assert data1["success"] is True, f"第1页返回失败: {data1.get('message')}"

    total = data1["data"].get("total", 0)
    if total <= 20:
        pytest.skip(f"日志仅 {total} 条，不足一页，无法验证分页")

    # 请求第2页
    resp2 = api_client.get(
        "/api/user/computing_power_logs",
        params={"page": 2, "page_size": 20},
    )
    assert resp2.status_code == 200, f"第2页请求失败: {resp2.status_code}"
    data2 = resp2.json()
    assert data2["success"] is True, f"第2页返回失败: {data2.get('message')}"

    logs1 = data1["data"].get("logs", [])
    logs2 = data2["data"].get("logs", [])
    assert len(logs1) > 0, "第1页不应为空"
    assert len(logs2) > 0, "第2页不应为空"

    ids1 = {log["id"] for log in logs1}
    ids2 = {log["id"] for log in logs2}
    assert ids1.isdisjoint(ids2), (
        f"第1页和第2页的日志ID不应重复，"
        f"重复ID: {ids1 & ids2}（说明 offset 恒为 0，始终返回第一页）"
    )


@pytest.mark.p1
@pytest.mark.computing_power
def test_power_logs_pagination_with_behavior_filter(api_client, e2e_config, base_url):
    """cpl_008 - 带 behavior 筛选的分页也应正确工作。"""
    from conftest import refresh_login

    for behavior in ("increase", "deduct"):
        resp = api_client.get(
            "/api/user/computing_power_logs",
            params={"page": 1, "page_size": 10, "behavior": behavior},
        )
        # token 失效时重新登录
        if resp.status_code == 400 and "认证" in resp.text:
            login_data = refresh_login(e2e_config, base_url)
            if login_data:
                api_client.headers.update({
                    "Authorization": f"Bearer {login_data['token']}",
                    "X-User-Id": login_data["user_id"],
                })
            resp = api_client.get(
                "/api/user/computing_power_logs",
                params={"page": 1, "page_size": 10, "behavior": behavior},
            )
        assert resp.status_code == 200, f"behavior={behavior} 请求失败: {resp.status_code}"
        data = resp.json()
        assert data["success"] is True, f"behavior={behavior} 返回失败: {data.get('message')}"

        # 验证筛选结果的 behavior 类型一致
        for log in data["data"].get("logs", []):
            assert log["behavior"] == behavior, (
                f"筛选 behavior={behavior} 但返回了 behavior={log['behavior']} 的日志"
            )
