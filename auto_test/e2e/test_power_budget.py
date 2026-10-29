"""
单次任务算力上限（PowerBudget）端到端测试（2026-10 新增功能，api/user.py
GET/PUT/DELETE /api/user/power-budget）。

背景：该路由曾在商业版漏挂（fix 796d6db2），属易回归点——API 级 e2e
守护「社区/商业双版本路由都在」；UI 用例守护剧本编排页输入框与服务端
状态同步（保存失败可见/恢复默认按钮语义在 web/tests 已单测覆盖）。

每个用例结束 best-effort DELETE 恢复平台默认，不污染账号偏好。
"""
import httpx
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.user,
]

# 纯 API、无外部依赖（不需要媒体挡板/算力），可进 CI push 门禁


def _cleanup(api_client):
    try:
        api_client.delete("/api/user/power-budget")
    except Exception:
        pass


@pytest.mark.ci_smoke
@pytest.mark.p0
def test_power_budget_requires_login(base_url):
    """power_budget_001 - 未登录 GET 401（路由必须存在于社区/商业双版本）"""
    resp = httpx.get(f"{base_url}/api/user/power-budget", timeout=15)
    assert resp.status_code == 401, f"未登录应 401: {resp.status_code} {resp.text}"


@pytest.mark.ci_smoke
@pytest.mark.p0
def test_power_budget_get_default_payload(api_client):
    """power_budget_002 - GET 默认返回 {limit, is_custom=false, default_limit}"""
    try:
        resp = api_client.get("/api/user/power-budget")
        assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
        data = resp.json()
        assert data.get("code") == 0
        payload = data["data"]
        assert set(payload.keys()) >= {"limit", "is_custom", "default_limit"}
        assert payload["limit"] == payload["default_limit"], \
            "无自定义偏好时 limit 应等于平台默认"
        assert payload["is_custom"] is False
    finally:
        _cleanup(api_client)


@pytest.mark.ci_smoke
@pytest.mark.p0
def test_power_budget_put_invalid_rejected(api_client):
    """power_budget_003 - PUT 负数 400 且不落库"""
    try:
        resp = api_client.put("/api/user/power-budget", json={"limit": -1})
        assert resp.status_code == 400, f"负数应 400: {resp.status_code} {resp.text}"

        after = api_client.get("/api/user/power-budget").json()["data"]
        assert after["is_custom"] is False, "非法值不得落库"
    finally:
        _cleanup(api_client)


@pytest.mark.ci_smoke
@pytest.mark.p0
def test_power_budget_put_and_roundtrip(api_client):
    """power_budget_004 - PUT 合法值生效，GET 回读一致，DELETE 回退默认"""
    try:
        resp = api_client.put("/api/user/power-budget", json={"limit": 66})
        assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["limit"] == 66
        assert data["data"]["is_custom"] is True

        after = api_client.get("/api/user/power-budget").json()["data"]
        assert after["limit"] == 66
        assert after["is_custom"] is True

        # 0 表示不限制，同样是合法自定义值
        resp = api_client.put("/api/user/power-budget", json={"limit": 0})
        assert resp.status_code == 200
        assert resp.json()["data"]["is_custom"] is True

        # DELETE 回退平台默认
        resp = api_client.delete("/api/user/power-budget")
        assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
        reset = resp.json()["data"]
        assert reset["is_custom"] is False
        assert reset["limit"] == reset["default_limit"]
    finally:
        _cleanup(api_client)


@pytest.mark.p1
def test_power_budget_input_synced_on_script_writer_page(api_client, page, base_url):
    """power_budget_005 - 剧本编排页输入框初值与服务端生效值一致（UI 轻链路）"""
    try:
        api_client.put("/api/user/power-budget", json={"limit": 66})
        page.goto(f"{base_url}/script-writer")
        input_el = page.locator("#power-budget-input")
        input_el.wait_for(state="visible", timeout=20000)
        # 等待 loadPowerBudgetPreference 异步回填
        page.wait_for_function(
            "() => document.getElementById('power-budget-input')?.value === '66'",
            timeout=15000,
        )
        assert input_el.input_value() == "66"
    finally:
        _cleanup(api_client)
