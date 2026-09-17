"""
月度订阅（充值中心-月度订阅 Tab）UI E2E 测试。

通过 page.route() mock /api/subscription/* 响应，覆盖本次订阅改动的界面表现：
  - 新用户（first_bonus_eligible=true）：套餐卡片展示「首期订阅加赠 X 算力」
  - 签约未生效（sign_not_effective=true）：展示琥珀色引导横幅（区别于用户主动解约文案）
  - 老用户（first_bonus_eligible=false）：不展示加赠标签

需要目标环境的 is_local=false（否则「算力充值」按钮只弹提示不打开弹窗）。
"""
import json as _json

import pytest

# 与 config/subscription_config.py MONTHLY_SUBSCRIPTION_PLANS 保持一致
SUBSCRIPTION_PLANS = [
    {"plan_id": 101, "name": "入门版", "price": 29.9, "computing_power": 328,
     "granted_after_commission": 328, "first_period_bonus": 100, "template_id": "223101", "badge": None},
    {"plan_id": 102, "name": "标准版", "price": 59.9, "computing_power": 808,
     "granted_after_commission": 808, "first_period_bonus": 200, "template_id": "223102", "badge": None},
    {"plan_id": 103, "name": "专业版", "price": 129.0, "computing_power": 2148,
     "granted_after_commission": 2148, "first_period_bonus": 300, "template_id": "223103", "badge": None},
    {"plan_id": 104, "name": "旗舰版", "price": 299.0, "computing_power": 5598,
     "granted_after_commission": 5598, "first_period_bonus": 500, "template_id": "223104", "badge": None},
]

# 各场景订阅状态（对应 services.subscription_service.get_subscription_status 返回）
STATUS_NEW_USER = {"subscribed": False, "status": "none", "first_bonus_eligible": True}
STATUS_SIGN_NOT_EFFECTIVE = {
    "subscribed": True, "status": "terminated", "sign_not_effective": True,
    "current_period_end": "2026-10-17T09:53:55", "first_bonus_eligible": False,
}
STATUS_RETURNING_USER = {"subscribed": False, "status": "none", "first_bonus_eligible": False}


def _mock_subscription_api(page, subscription):
    """mock 订阅相关 API；其余请求透传给真实服务（复用 live_auth 注入的登录态）"""
    def _handler(route):
        url = route.request.url
        if "/api/subscription/plans" in url or "/api/subscription/status" in url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({
                    "success": True,
                    "plans": SUBSCRIPTION_PLANS,
                    "subscription": subscription,
                }),
            )
        elif "/api/recharge/packages" in url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"success": True, "packages": []}),
            )
        else:
            route.continue_()

    page.route("**/api/**", _handler)


def _open_subscription_tab(page, base_url, subscription):
    """打开充值中心（默认落在月度订阅 Tab），等待套餐卡片渲染"""
    _mock_subscription_api(page, subscription)
    page.goto(base_url, wait_until="domcontentloaded")
    # 头部「算力充值」按钮（$t('recharge')）；弹窗未打开时页面唯一匹配
    page.locator("button.btn.secondary", has_text="算力充值").first.click()
    page.locator(".sub-plan-card").first.wait_for()
    return page


@pytest.mark.subscription
@pytest.mark.p2
class TestSubscriptionBonusDisplay:
    """首订加赠标签按资格展示"""

    def test_new_user_sees_first_period_bonus(self, browser_context, base_url):
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, STATUS_NEW_USER)

        tags = page.locator(".sub-plan-bonus")
        assert tags.count() == 4, "新用户应看到全部 4 档的首期加赠标签"
        assert "首期订阅加赠 100 算力" in tags.first.inner_text()

    def test_returning_user_no_bonus_tag(self, browser_context, base_url):
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, STATUS_RETURNING_USER)

        assert page.locator(".sub-plan-bonus").count() == 0, \
            "已有历史成功签约的老用户不应再看到首期加赠标签"

    def test_new_user_bonus_text_in_payment_panel(self, browser_context, base_url):
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, STATUS_NEW_USER)

        page.locator(".sub-plan-card").first.click()
        panel_text = page.locator(".sub-payment-panel").inner_text()
        assert "首期订阅加赠 100 算力" in panel_text


@pytest.mark.subscription
@pytest.mark.p2
class TestSubscriptionSignNotEffectiveGuide:
    """支付成功但签约未生效：引导横幅 + 单期权益文案（区别于用户主动解约）"""

    def test_guide_banner_shown(self, browser_context, base_url):
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, STATUS_SIGN_NOT_EFFECTIVE)

        banner = page.locator(".package-intro-warning")
        assert banner.is_visible(), "签约未生效应展示引导横幅"
        banner_text = banner.inner_text()
        assert "本月会员已付费" in banner_text
        assert "自动续费" in banner_text
        # 引导重新开通持续享受优惠，而非"您已取消订阅"的解约文案
        assert "持续享受" in banner_text
        assert "您已取消订阅" not in banner_text

    def test_normal_terminated_shows_cancel_copy(self, browser_context, base_url):
        """用户主动解约：保持原解约文案，不出现引导横幅"""
        subscription = {
            "subscribed": True, "status": "terminated",
            "current_period_end": "2026-10-17T09:53:55", "first_bonus_eligible": False,
        }
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, subscription)

        assert page.locator(".package-intro-warning").count() == 0
        assert "您已取消订阅" in page.locator(".package-intro").inner_text()
