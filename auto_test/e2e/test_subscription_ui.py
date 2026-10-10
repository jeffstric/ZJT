"""
月度订阅（充值中心-月度订阅 Tab）UI E2E 测试。

通过 page.route() mock /api/subscription/* 响应，覆盖本次订阅改动的界面表现：
  - 新用户（first_bonus_eligible=true）：入门版首月 18.8、首期算力 328+40=368，
    小字标注「之后每期 328 算力」，并播放价格/算力强调动画
  - 新用户：套餐卡片展示「比直接购买多约 X 算力」对比角标（数据驱动，按充值包单价折算）
  - 签约未生效（sign_not_effective=true）：展示琥珀色引导横幅（区别于用户主动解约文案）
  - 老用户（first_bonus_eligible=false）：不展示 18.8 / +40，按每期 29.9 与 328 算力展示

is_local 由本文件 mock 的 /api/system/server-config 强制为 false：本地部署
（config is_local=true）时「算力充值」按钮只 alert 提示、不打开弹窗
（index_app.js handleRechargeClick），不 mock 则本地环境全部用例超时。
"""
import json as _json

import pytest

# 与 config/subscription_config.py MONTHLY_SUBSCRIPTION_PLANS 保持一致
# 入门版：首期优惠 18.8、加赠 40；续费价仍 29.9
SUBSCRIPTION_PLANS = [
    {"plan_id": 101, "name": "入门版", "price": 29.9, "first_period_price": 18.8,
     "computing_power": 328, "granted_after_commission": 328, "first_period_bonus": 40,
     "template_id": "224144", "badge": None},
    {"plan_id": 102, "name": "标准版", "price": 59.9, "computing_power": 808,
     "granted_after_commission": 808, "first_period_bonus": 400, "template_id": "223102", "badge": None},
    {"plan_id": 103, "name": "专业版", "price": 129.0, "computing_power": 2148,
     "granted_after_commission": 2148, "first_period_bonus": 600, "template_id": "223103", "badge": None},
    {"plan_id": 104, "name": "旗舰版", "price": 299.0, "computing_power": 5598,
     "granted_after_commission": 5598, "first_period_bonus": 1000, "template_id": "223104", "badge": None},
]

# 算力充值套餐 mock（与 config/constant.py RECHARGE_PACKAGES 结构一致）。
# 含 0.1 元首充福利包：用于验证对比折算将其排除（否则参考单价被促销包扭曲）。
RECHARGE_PACKAGES = [
    {"package_id": 5, "computing_power": 99, "price": 0.1, "description": "首充福利 99",
     "granted_computing_power": 99},
    {"package_id": 1, "computing_power": 88, "price": 9.9, "description": "算力包 88",
     "granted_computing_power": 88},
    {"package_id": 2, "computing_power": 508, "price": 49.9, "description": "算力包 508",
     "granted_computing_power": 508},
]

# 各场景订阅状态（对应 services.subscription_service.get_subscription_status 返回）
STATUS_NEW_USER = {"subscribed": False, "status": "none", "first_bonus_eligible": True}
STATUS_SIGN_NOT_EFFECTIVE = {
    "subscribed": True, "status": "terminated", "sign_not_effective": True,
    "current_period_end": "2026-10-17T09:53:55", "first_bonus_eligible": False,
}
STATUS_RETURNING_USER = {"subscribed": False, "status": "none", "first_bonus_eligible": False}


def _mock_subscription_api(page, subscription, recharge_packages=None):
    """mock 订阅相关 API；其余请求透传给真实服务（复用 live_auth 注入的登录态）"""
    def _handler(route):
        url = route.request.url
        if "/api/system/server-config" in url:
            # 本地部署 is_local=true 时「算力充值」只 alert 不开弹窗，强制 false
            route.fulfill(
                status=200,
                content_type="application/json",
                body=_json.dumps({"code": 0, "data": {"is_local": False}}),
            )
        elif "/api/subscription/plans" in url or "/api/subscription/status" in url:
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
                body=_json.dumps({"success": True, "packages": recharge_packages or []}),
            )
        else:
            route.continue_()

    page.route("**/api/**", _handler)


def _open_subscription_tab(page, base_url, subscription, recharge_packages=None):
    """打开充值中心（默认落在月度订阅 Tab），等待套餐卡片渲染"""
    _mock_subscription_api(page, subscription, recharge_packages)
    page.goto(base_url, wait_until="domcontentloaded")
    # 头部「算力充值」按钮（$t('recharge')）；弹窗未打开时页面唯一匹配
    page.locator("button.btn.secondary", has_text="算力充值").first.click()
    page.locator(".sub-plan-card").first.wait_for()
    return page


@pytest.mark.subscription
@pytest.mark.p2
class TestSubscriptionBonusDisplay:
    """首订加赠并入首期算力展示（不再独立角标）"""

    def test_new_user_sees_merged_first_period_power(self, browser_context, base_url):
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, STATUS_NEW_USER)

        page.locator(".sub-plan-card.sub-intro-done").first.wait_for(timeout=8000)
        assert page.locator(".sub-plan-bonus").count() == 0, "不应再出现独立的首期加赠角标"
        card = page.locator(".sub-plan-card").first.inner_text()
        assert "18.8" in card
        assert "之后 ¥29.9/月" in card
        power = page.locator(".sub-plan-power").first.inner_text()
        assert "368" in power, "入门版首期应为 328+40=368 算力"
        assert "首期" in power
        assert "之后每期 328 算力" in power, "小字应标注之后每期的常规到账算力"

    def test_multiple_label_shown_except_base_plan(self, browser_context, base_url):
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, STATUS_NEW_USER)

        # 「≈ 基础档 X 倍算力」保留：除入门版（最低档）外均展示
        mults = page.locator(".sub-plan-mult")
        assert mults.count() == 3, "标准/专业/旗舰版应显示倍数标注，入门版不显示"
        assert "2.5 倍算力" in mults.first.inner_text()

    def test_returning_user_no_bonus_tag(self, browser_context, base_url):
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, STATUS_RETURNING_USER)

        assert page.locator(".sub-plan-bonus").count() == 0, \
            "已有历史成功签约的老用户不应再看到首期加赠标签"
        assert page.locator(".sub-intro-done").count() == 0
        card = page.locator(".sub-plan-card").first.inner_text()
        assert "29.9" in card
        assert "18.8" not in card
        power = page.locator(".sub-plan-power").first.inner_text()
        assert "328" in power
        assert "368" not in power
        assert "首期" not in power
        assert "之后每期" not in power

    def test_new_user_bonus_text_in_payment_panel(self, browser_context, base_url):
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, STATUS_NEW_USER)

        page.locator(".sub-plan-card.sub-intro-done").first.wait_for(timeout=8000)
        page.locator(".sub-plan-card").first.click()
        panel_text = page.locator(".sub-payment-panel").inner_text()
        assert "18.8" in panel_text
        assert "首期到账 368 算力" in panel_text
        assert "之后每期 328 算力" in panel_text


@pytest.mark.subscription
@pytest.mark.p2
class TestSubscriptionVsDirectSave:
    """「比直接购买多约 X 算力」对比角标（参考单价取最低价的常规算力包，排除首充福利）"""

    def test_new_user_sees_save_badge(self, browser_context, base_url):
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, STATUS_NEW_USER, recharge_packages=RECHARGE_PACKAGES)

        page.locator(".sub-plan-card.sub-intro-done").first.wait_for(timeout=8000)
        badges = page.locator(".sub-plan-save")
        assert badges.count() == 4, "全部 4 档均应按充值包单价折算出更多算力"
        # 入门版：首期 368 - round(18.8 × 88/9.9)=167 → 多约 201 算力
        # （0.1 元首充福利包必须被排除，否则参考单价失真、角标不展示）
        assert "比直接购买多约 201 算力" in badges.first.inner_text()

    def test_returning_user_save_badge_uses_regular_power(self, browser_context, base_url):
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, STATUS_RETURNING_USER, recharge_packages=RECHARGE_PACKAGES)

        # 老用户无首订加赠：按每期常规算力 328 对比 → 328-266=62，仍展示角标
        badges = page.locator(".sub-plan-save")
        assert badges.count() == 4
        assert "比直接购买多约 62 算力" in badges.first.inner_text()

    def test_no_badge_without_recharge_packages(self, browser_context, base_url):
        page = browser_context.new_page()
        # 充值套餐未加载（空列表）时不展示角标，避免出现无参照的失真数字
        _open_subscription_tab(page, base_url, STATUS_NEW_USER, recharge_packages=[])

        assert page.locator(".sub-plan-save").count() == 0


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


STATUS_SIGNING = {"subscribed": False, "status": "signing", "first_bonus_eligible": True}


@pytest.mark.subscription
@pytest.mark.p2
class TestSubscriptionSigningShowsPlans:
    """签约进行中：提示条不阻塞套餐列表，用户可直接重新发起（后端自动作废旧签约）"""

    def test_signing_shows_notice_and_plan_list(self, browser_context, base_url):
        page = browser_context.new_page()
        _open_subscription_tab(page, base_url, STATUS_SIGNING)

        notice = page.locator(".sub-status-card", has_text="签约进行中")
        assert notice.is_visible(), "签约中提示条应展示"
        assert "重新发起" in notice.inner_text(), "提示应引导可直接重新发起"
        # 套餐列表不被 signing 状态隐藏，用户无需等 2 小时清理
        assert page.locator(".sub-plan-card").count() == 4, "签约中仍应展示全部套餐可选"
