"""
月度订阅（微信委托代扣·周期扣费）单元测试

覆盖：
  - V2 MD5 签名/验签（含空值排除、密钥未配置降级）
  - V2 XML 构造/解析往返
  - 单据号格式约束（微信 32 字符、协议号仅字母数字）
  - 预扣费通知等待期计算
  - 支付/扣款回调结算状态机（mock 模型层，同步测试 + asyncio.run 惯例）
  - 签约/解约回调处理（mock 模型层）
"""
import asyncio
import hashlib
from datetime import datetime, timedelta

import pytest

from config.constant import (
    SubscriptionOrderStatus,
    WxContractStatus,
)
from config.subscription_config import get_subscription_plan
from utils.wx_papay_util import WxPapayUtil, dict_to_xml, xml_to_dict


def make_util(api_v2_key="test_v2_key_32_bytes_1234567890a"):
    return WxPapayUtil(
        app_id="wx1234567890abcdef",
        mch_id="1900000109",
        api_v2_key=api_v2_key,
        plan_template_id="1234567",
    )


# ==================== 签名/验签 ====================

class TestV2Sign:
    def test_sign_v2_matches_manual_md5(self):
        util = make_util()
        params = {"appid": "wx123", "mch_id": "1900", "total_fee": 1990, "body": "月度会员"}
        # 手工按官方算法计算期望值：ASCII 升序 k=v& + &key=
        raw = "appid=wx123&body=月度会员&mch_id=1900&total_fee=1990&key=" + util.api_v2_key
        expected = hashlib.md5(raw.encode("utf-8")).hexdigest().upper()
        assert util._sign_v2(params) == expected

    def test_sign_excludes_empty_and_sign_field(self):
        util = make_util()
        base = {"b": "2", "a": "1"}
        with_extra = {"b": "2", "a": "1", "empty": "", "sign": "SHOULDBEIGNORED"}
        assert util._sign_v2(base) == util._sign_v2(with_extra)

    def test_verify_v2_sign_ok(self):
        util = make_util()
        params = {"appid": "wx123", "mch_id": "1900", "nonce_str": "abc"}
        params["sign"] = util._sign_v2(params)
        assert util.verify_v2_sign(params) is True

    def test_verify_v2_sign_tampered(self):
        util = make_util()
        params = {"appid": "wx123", "mch_id": "1900", "total_fee": 100}
        params["sign"] = util._sign_v2(params)
        params["total_fee"] = 1  # 篡改金额
        assert util.verify_v2_sign(params) is False

    def test_verify_v2_sign_missing_sign(self):
        util = make_util()
        assert util.verify_v2_sign({"appid": "wx123"}) is False

    def test_verify_v2_sign_empty_key_degrades(self):
        util = make_util(api_v2_key="")
        # 密钥未配置：开发环境降级跳过（返回 True）
        assert util.verify_v2_sign({"appid": "wx123"}) is True


# ==================== XML 构造/解析 ====================

class TestXml:
    def test_roundtrip_with_chinese_and_cdata(self):
        params = {"body": "月度会员订阅-推荐", "total_fee": 1990, "return_code": "SUCCESS"}
        parsed = xml_to_dict(dict_to_xml(params))
        assert parsed["body"] == "月度会员订阅-推荐"
        assert parsed["total_fee"] == "1990"
        assert parsed["return_code"] == "SUCCESS"

    def test_parse_wechat_official_sample(self):
        sample = """
        <xml>
          <return_code><![CDATA[SUCCESS]]></return_code>
          <result_code><![CDATA[SUCCESS]]></result_code>
          <sign><![CDATA[C380BEC2BFD727A4B6845133519F3AD6]]></sign>
          <mch_id>10010404</mch_id>
          <contract_code>100001256</contract_code>
          <openid><![CDATA[onqOjjmM1tad-3ROpncN-yUfa6ua]]></openid>
          <change_type><![CDATA[ADD]]></change_type>
          <operate_time><![CDATA[2015-07-01 10:00:00]]></operate_time>
          <contract_id><![CDATA[Wx15463511252015071056489715]]></contract_id>
        </xml>
        """
        parsed = xml_to_dict(sample)
        assert parsed["change_type"] == "ADD"
        assert parsed["contract_code"] == "100001256"
        assert parsed["mch_id"] == "10010404"

    def test_none_values_skipped(self):
        xml = dict_to_xml({"a": "1", "b": None})
        assert "<b>" not in xml and "<a>" in xml

    def test_invalid_xml_returns_empty(self):
        assert xml_to_dict("not-a-xml<<<") == {}


# ==================== 单据号约束 ====================

class TestIdGeneration:
    def test_order_id_within_wechat_limit(self):
        order_id = WxPapayUtil.generate_subscription_order_id()
        assert len(order_id) <= 32
        assert order_id.startswith("SUB_")

    def test_contract_code_alnum_only(self):
        code = WxPapayUtil.generate_contract_code()
        assert code.isalnum()
        assert len(code) <= 64
        assert code.startswith("SUBC")


# ==================== 套餐配置 ====================

class TestPlans:
    def test_get_plan_found(self):
        plan = get_subscription_plan(102)
        assert plan and plan["computing_power"] == 1000
        assert plan["first_period_bonus"] == 200

    def test_get_plan_not_found(self):
        assert get_subscription_plan(999) is None


# ==================== 等待期计算 ====================

class TestDeductTiming:
    def test_prenotify_wait_end(self):
        from services.subscription_service import _prenotify_wait_end
        # 9月7日 15:00 下发通知 → 当日(9/7)+次日(9/8)为等待期 → 9/9 00:00 起可扣
        sent = datetime(2026, 9, 7, 15, 30)
        assert _prenotify_wait_end(sent) == datetime(2026, 9, 9, 0, 0)

    def test_prenotify_wait_end_cross_month(self):
        from services.subscription_service import _prenotify_wait_end
        sent = datetime(2026, 9, 30, 8, 0)
        assert _prenotify_wait_end(sent) == datetime(2026, 10, 2, 0, 0)


# ==================== 回调状态机（mock 模型层） ====================

class _FakeOrder:
    def __init__(self, **kw):
        self.order_id = "SUB_1_a"
        self.contract_code = "SUBC1"
        self.user_id = 1
        self.subscription_plan_id = 102
        self.period_index = 2
        self.amount = 39.9
        self.computing_power = 3000
        self.period_start = datetime(2026, 9, 10)
        self.period_end = datetime(2026, 10, 10)
        self.status = SubscriptionOrderStatus.CONFIRMING
        self.transaction_id = None
        self.prenotify_sent_at = datetime(2026, 9, 7, 10, 0)
        self.__dict__.update(kw)


@pytest.fixture
def patched_service(monkeypatch):
    """mock 掉服务层的模型依赖与算力发放，隔离单测"""
    from services import subscription_service as svc

    calls = {
        "mark_paid": [], "grant": [], "update_period": [],
        "mark_failed": [], "close": [], "mark_confirming": [],
        "mark_signed": [], "mark_terminated": [], "settle": [],
    }

    monkeypatch.setattr(svc, "get_papay_util", lambda *a, **kw: make_util())

    async def fake_perseids(endpoint=None, **kw):
        if endpoint == 'commission/settle':
            calls["settle"].append(kw.get('data'))
            return True, 'ok', {'granted_computing_power': 2400}
        return True, 'ok', {}
    monkeypatch.setattr(svc, "async_make_perseids_request", fake_perseids)
    monkeypatch.setattr(
        svc.SubscriptionOrdersModel, "get_by_order_id",
        staticmethod(lambda order_id: _FakeOrder(order_id=order_id)),
    )
    monkeypatch.setattr(
        svc.SubscriptionOrdersModel, "mark_paid",
        staticmethod(lambda order_id, txn: calls["mark_paid"].append((order_id, txn)) or 1),
    )
    monkeypatch.setattr(
        svc.SubscriptionOrdersModel, "set_grant_flag",
        staticmethod(lambda order_id, flag: None),
    )
    monkeypatch.setattr(
        svc.SubscriptionOrdersModel, "mark_failed",
        staticmethod(lambda order_id, err_code, err_msg, next_retry_at=None, **kw:
                     calls["mark_failed"].append(order_id) or 1),
    )
    monkeypatch.setattr(
        svc.SubscriptionOrdersModel, "close",
        staticmethod(lambda order_id, c=None, m=None: calls["close"].append(order_id) or 1),
    )
    monkeypatch.setattr(
        svc.SubscriptionOrdersModel, "mark_confirming",
        staticmethod(lambda order_id: calls["mark_confirming"].append(order_id) or 1),
    )
    monkeypatch.setattr(
        svc.WxPapayContractsModel, "update_period",
        staticmethod(lambda code, s, e: calls["update_period"].append((code, s, e)) or 1),
    )
    monkeypatch.setattr(
        svc.WxPapayContractsModel, "mark_signed",
        staticmethod(lambda code, cid, openid=None: calls["mark_signed"].append((code, cid)) or 1),
    )
    monkeypatch.setattr(
        svc.WxPapayContractsModel, "mark_terminated",
        staticmethod(lambda code, mode=None, remark=None: calls["mark_terminated"].append(code) or 1),
    )

    async def fake_grant(user_id, power, txn):
        calls["grant"].append((user_id, power, txn))
        return True
    monkeypatch.setattr(svc, "_grant_computing_power", fake_grant)
    return svc, calls


def _signed_pay_success_params(util):
    params = {
        "return_code": "SUCCESS", "result_code": "SUCCESS",
        "out_trade_no": "SUB_1_a", "transaction_id": "4200001234",
        "total_fee": "3990", "contract_id": "Wx154abc",
    }
    params["sign"] = util._sign_v2(params)
    return params


class TestPayCallback:
    def test_success_settles_and_extends_period(self, patched_service):
        svc, calls = patched_service
        util = make_util()
        ok = asyncio.run(svc.handle_pay_callback(_signed_pay_success_params(util)))
        assert ok is True
        assert calls["mark_paid"] == [("SUB_1_a", "4200001234")]
        # 续期单（period_index=2）：基础算力 3000 经抽佣结算后到账 2400，无赠送
        assert calls["settle"] == [{
            "user_id": 1, "order_id": "SUB_1_a", "transaction_id": "4200001234",
            "package_id": 102, "price": 39.9, "computing_power": 3000,
        }]
        assert calls["grant"] == [(1, 2400, "4200001234")]
        # 续期单：周期用订单预生成区间
        assert calls["update_period"] == [("SUBC1", datetime(2026, 9, 10), datetime(2026, 10, 10))]

    def test_first_period_grants_bonus(self, patched_service):
        """首期（period_index=1）：抽成后到账 + 首订赠送，赠送不参与抽佣"""
        svc, calls = patched_service
        util = make_util()
        params = _signed_pay_success_params(util)
        # 构造首期订单：套餐 102 基础 1000，赠送 200
        import services.subscription_service as real_svc

        def _first_order(order_id):
            return _FakeOrder(order_id=order_id, period_index=1, computing_power=1000)
        svc.SubscriptionOrdersModel.get_by_order_id = staticmethod(_first_order)
        ok = asyncio.run(real_svc.handle_pay_callback(params))
        assert ok is True
        assert calls["settle"][0]["computing_power"] == 1000
        # 抽佣后 2400（fake settle 固定返回值）+ 赠送 200 = 2600
        assert calls["grant"] == [(1, 2400 + 200, "4200001234")]

    def test_sign_verification_failure_rejected(self, patched_service):
        svc, _ = patched_service
        params = _signed_pay_success_params(make_util())
        params["total_fee"] = "1"  # 篡改
        ok = asyncio.run(svc.handle_pay_callback(params))
        assert ok is False

    def test_failed_renewal_schedules_retry(self, patched_service):
        svc, calls = patched_service
        util = make_util()
        params = {
            "return_code": "SUCCESS", "result_code": "FAIL",
            "err_code": "NOTENOUGH", "err_code_des": "余额不足",
            "out_trade_no": "SUB_1_a",
        }
        params["sign"] = util._sign_v2(params)
        ok = asyncio.run(svc.handle_pay_callback(params))
        assert ok is True
        assert calls["mark_failed"] == ["SUB_1_a"]
        assert calls["mark_paid"] == []

    def test_unknown_order_returns_false(self, patched_service, monkeypatch):
        svc, _ = patched_service
        monkeypatch.setattr(
            svc.SubscriptionOrdersModel, "get_by_order_id",
            staticmethod(lambda order_id: None),
        )
        util = make_util()
        ok = asyncio.run(svc.handle_pay_callback(_signed_pay_success_params(util)))
        assert ok is False


class TestContractCallback:
    def _signed(self, util, change_type, **extra):
        params = {
            "return_code": "SUCCESS", "result_code": "SUCCESS",
            "mch_id": "1900000109", "contract_code": "SUBC1",
            "openid": "oX1", "change_type": change_type,
            "operate_time": "2026-09-09 10:00:00",
            "contract_id": "Wx154abc", "request_serial": "100",
        }
        params.update(extra)
        params["sign"] = util._sign_v2(params)
        return params

    def test_add_marks_signed(self, patched_service, monkeypatch):
        svc, calls = patched_service
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_by_contract_code",
            staticmethod(lambda code: object()),
        )
        util = make_util()
        ok = asyncio.run(svc.handle_contract_callback(self._signed(util, "ADD")))
        assert ok is True
        assert calls["mark_signed"] == [("SUBC1", "Wx154abc")]

    def test_delete_marks_terminated(self, patched_service, monkeypatch):
        svc, calls = patched_service
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_by_contract_code",
            staticmethod(lambda code: object()),
        )
        util = make_util()
        ok = asyncio.run(svc.handle_contract_callback(
            self._signed(util, "DELETE", contract_termination_mode="2")
        ))
        assert ok is True
        assert calls["mark_terminated"] == ["SUBC1"]


# ==================== 续期订单创建（模式区分） ====================

class TestCreateRenewalOrders:
    def _patch_contract(self, svc, monkeypatch):
        class C:
            contract_code = "SUBC1"
            contract_id = "Wx154abc"
            user_id = 1
            subscription_plan_id = 102
            current_period_end = datetime.now() + timedelta(days=2)
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_renewal_due_contracts",
            staticmethod(lambda lead: [C()]),
        )
        return C

    def test_direct_mode_creates_order_without_prenotify(self, monkeypatch):
        from services import subscription_service as svc

        created = {}
        prenotify_calls = []
        monkeypatch.setattr(svc, "get_papay_util", lambda: make_util())

        class _Orders:
            @staticmethod
            def get_latest_by_contract(code):
                class Paid:
                    status = svc.SubscriptionOrderStatus.PAID
                    period_index = 1
                    period_end = datetime.now() - timedelta(days=1)
                    prenotify_sent_at = None
                    order_id = "SUB_OLD"
                return Paid()

            @staticmethod
            def create(**kw):
                created.update(kw)
                created["order_id"] = "SUB_NEW"

            @staticmethod
            def mark_prenotify_sent(order_id):
                prenotify_calls.append(order_id)

        monkeypatch.setattr(svc, "SubscriptionOrdersModel", _Orders)
        self._patch_contract(svc, monkeypatch)

        async def fake_prenotify(*a, **kw):
            prenotify_calls.append("CALLED")
            return True, {}
        monkeypatch.setattr(svc.WxPapayUtil, "pre_deduct_notify", staticmethod(fake_prenotify))
        monkeypatch.setattr(svc.SubscriptionConstants, "DEDUCT_MODE", "direct")

        asyncio.run(svc._create_renewal_orders())
        # direct 模式：创建续期订单，但不下发预扣费通知
        assert created.get("period_index") == 2
        assert created.get("subscription_plan_id") == 102
        assert prenotify_calls == []

    def test_pre_notify_mode_sends_prenotify(self, monkeypatch):
        from services import subscription_service as svc

        prenotify_calls = []
        monkeypatch.setattr(svc, "get_papay_util", lambda: make_util())

        class _Orders:
            @staticmethod
            def get_latest_by_contract(code):
                class Pending:
                    status = svc.SubscriptionOrderStatus.PENDING_PAY
                    period_index = 2
                    period_end = datetime.now() + timedelta(days=28)
                    prenotify_sent_at = None
                    order_id = "SUB_NEW"
                return Pending()

            @staticmethod
            def create(**kw):
                pass

            @staticmethod
            def mark_prenotify_sent(order_id):
                prenotify_calls.append(order_id)

        monkeypatch.setattr(svc, "SubscriptionOrdersModel", _Orders)
        self._patch_contract(svc, monkeypatch)

        def fake_prenotify(*a, **kw):
            prenotify_calls.append("SENT")
            return True, {}
        monkeypatch.setattr(svc.WxPapayUtil, "pre_deduct_notify", staticmethod(fake_prenotify))
        monkeypatch.setattr(svc.SubscriptionConstants, "DEDUCT_MODE", "pre_notify")

        asyncio.run(svc._create_renewal_orders())
        assert "SENT" in prenotify_calls and "SUB_NEW" in prenotify_calls


# ==================== 订阅状态视图 ====================

class TestSubscriptionStatus:
    def test_none(self, monkeypatch):
        from services import subscription_service as svc
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_latest_by_user",
            staticmethod(lambda user_id: None),
        )
        assert svc.get_subscription_status(1) == {"subscribed": False, "status": "none"}

    def test_active(self, monkeypatch):
        from services import subscription_service as svc

        class C:
            status = WxContractStatus.ACTIVE
            subscription_plan_id = 102
            current_period_end = datetime.now() + timedelta(days=20)
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_latest_by_user",
            staticmethod(lambda user_id: C()),
        )
        status = svc.get_subscription_status(1)
        assert status["subscribed"] is True
        assert status["status"] == "active"
        assert status["next_deduct_date"] == C.current_period_end.date().isoformat()

    def test_active_but_period_expired(self, monkeypatch):
        from services import subscription_service as svc

        class C:
            status = WxContractStatus.ACTIVE
            subscription_plan_id = 102
            current_period_end = datetime.now() - timedelta(days=1)
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_latest_by_user",
            staticmethod(lambda user_id: C()),
        )
        status = svc.get_subscription_status(1)
        assert status["subscribed"] is False
        assert status["status"] == "expired"
