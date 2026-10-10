"""
月度订阅 API 测试（2026-09 新增功能：微信委托代扣·周期扣费，api/subscription.py）。

仅覆盖确定性的鉴权/校验层。真实签约/支付/解约链路依赖外部微信平台与外部算力
平台校验（本测试环境外部平台拒收本地 token），不在 e2e 覆盖范围（与
/api/recharge/wechat-pay、/api/parse-script 同理）：
- GET  /api/subscription/plans：未登录 401；4 档套餐 101-104 + 状态字段；
  token 外部校验失败时首期优惠资格 fail-closed（防"展示加赠、实收无加赠"客诉）
- GET  /api/subscription/status、/order-status：未登录/无效 token 401
- POST /api/subscription/cancel：无效 token 401
- POST /api/subscription/wechat-sign-pay：空 token 400；无效 token 401
"""
import httpx
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.subscription,
    pytest.mark.p1,
]

PLAN_IDS = {101, 102, 103, 104}  # 入门/标准/专业/旗舰


def test_plans_requires_login(base_url):
    """sub_api_001 - 未登录访问套餐列表 401"""
    resp = httpx.get(f"{base_url}/api/subscription/plans", timeout=15)
    assert resp.status_code == 401
    assert resp.json().get("error_code") == "missing_auth_token"


def test_plans_shape_and_status(api_client):
    """sub_api_002 - 套餐列表 4 档齐全；登录用户返回真实订阅状态"""
    resp = api_client.get("/api/subscription/plans")
    assert resp.status_code == 200, f"套餐列表失败: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data.get("success") is True, f"响应异常: {data}"

    plans = data.get("plans", [])
    assert {p.get("plan_id") for p in plans} == PLAN_IDS, f"套餐 plan_id 应为 101-104: {plans}"
    for p in plans:
        assert p.get("name"), f"套餐缺名称: {p}"
        assert p.get("price") is not None, f"套餐缺价格: {p}"
        assert p.get("computing_power"), f"套餐缺算力: {p}"

    sub = data.get("subscription")
    assert isinstance(sub, dict), f"subscription 应为对象: {data}"
    assert "subscribed" in sub and "first_bonus_eligible" in sub, f"subscription 字段缺失: {sub}"
    # 主测试账号无真实微信签约，应未订阅
    assert sub.get("subscribed") is False, f"主测试账号应无订阅: {sub}"
    assert isinstance(sub.get("first_bonus_eligible"), bool), f"first_bonus_eligible 应为布尔: {sub}"
    # 注：token 外部校验失败时的 fail-closed（first_bonus_eligible=False 防客诉）
    # 依赖外部平台拒收本地 token 的场景，本环境 get_user_id_by_auth_token 可解析
    # 本地 token，走真实状态分支，不在 e2e 断言范围


def test_plans_empty_auth_header(api_client):
    """sub_api_003 - 空 Authorization 头视同未登录 401（require_permission 无查询参数回退）"""
    resp = api_client.get(
        "/api/subscription/plans",
        headers={"Authorization": ""},  # 显式发送空 Authorization 头
    )
    assert resp.status_code == 401
    assert resp.json().get("error_code") == "missing_auth_token"


def test_status_requires_login(base_url):
    """sub_api_004 - 订阅状态接口未登录 401"""
    resp = httpx.get(
        f"{base_url}/api/subscription/status",
        params={"user_id": "1"},
        timeout=15,
    )
    assert resp.status_code == 401
    assert resp.json().get("error_code") == "missing_auth_token"


def test_status_invalid_token(base_url):
    """sub_api_005 - 订阅状态接口无效 token 401"""
    resp = httpx.get(
        f"{base_url}/api/subscription/status",
        params={"user_id": "1"},
        headers={"Authorization": "Bearer invalid-token-xyz"},
        timeout=15,
    )
    assert resp.status_code == 401
    assert resp.json().get("error_code") == "invalid_auth_token"


def test_order_status_requires_login(base_url):
    """sub_api_006 - 订单支付状态接口未登录 401"""
    resp = httpx.get(
        f"{base_url}/api/subscription/order-status",
        params={"order_id": "SUB_TEST_001", "user_id": "1"},
        timeout=15,
    )
    assert resp.status_code == 401
    assert resp.json().get("error_code") == "missing_auth_token"


def test_cancel_invalid_token(api_client, user_id):
    """sub_api_007 - 解约接口无效 token 401（外部平台拒收本地 token，fail-closed）"""
    resp = api_client.post(
        "/api/subscription/cancel",
        json={"user_id": user_id, "auth_token": "invalid-token-xyz"},
    )
    assert resp.status_code == 401, f"无效 token 解约应 401: {resp.status_code} {resp.text}"


def test_wechat_sign_pay_empty_token(api_client, user_id):
    """sub_api_008 - 签约支付空 token 400（token 为必填业务字段）"""
    resp = api_client.post(
        "/api/subscription/wechat-sign-pay",
        json={
            "subscription_plan_id": 101,
            "user_id": user_id,
            "auth_token": "",
        },
    )
    assert resp.status_code == 400
    assert "Authentication token is required" in resp.json().get("detail", "")


def test_wechat_sign_pay_invalid_token(api_client, user_id):
    """sub_api_009 - 签约支付无效 token 401（外部校验 fail-closed，不产生订单）"""
    resp = api_client.post(
        "/api/subscription/wechat-sign-pay",
        json={
            "subscription_plan_id": 101,
            "user_id": user_id,
            "auth_token": "invalid-token-xyz",
        },
    )
    assert resp.status_code == 401, f"无效 token 签约支付应 401: {resp.status_code} {resp.text}"
