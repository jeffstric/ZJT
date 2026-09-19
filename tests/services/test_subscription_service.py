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
        assert plan and plan["computing_power"] == 808
        # 2026-09-19 首订加赠全档翻倍：102 标准版 200 → 400
        assert plan["first_period_bonus"] == 400

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
        self.upgrade_from_contract_code = None
        self.first_bonus_granted = 0
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
        "bonus_flag": [],
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
        svc.SubscriptionOrdersModel, "get_latest_by_contract",
        staticmethod(lambda contract_code: None),
    )
    monkeypatch.setattr(
        svc.SubscriptionOrdersModel, "mark_first_bonus_granted",
        staticmethod(lambda order_id: calls["bonus_flag"].append(order_id) or 1),
    )
    # 默认合约仍签约中（PENDING）：模拟支付回调先于签约回调的典型时序，首赠顺延
    monkeypatch.setattr(
        svc.WxPapayContractsModel, "get_by_contract_code",
        staticmethod(lambda code: _FakeContract(status=WxContractStatus.PENDING, contract_code=code)),
    )
    monkeypatch.setattr(
        svc.WxPapayContractsModel, "exists_signed_contract",
        staticmethod(lambda user_id, exclude_contract_code=None: False),
    )
    # 默认无其它生效签约：新约生效后的"只保留一个订阅"清理无目标
    monkeypatch.setattr(
        svc.WxPapayContractsModel, "get_active_contracts_by_user",
        staticmethod(lambda user_id: []),
    )
    monkeypatch.setattr(
        svc.WxPapayContractsModel, "get_users_with_multiple_active_contracts",
        staticmethod(lambda limit=100: []),
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

    def test_first_period_grants_bonus_after_signed(self, patched_service):
        """首期签约成功后发放首订加赠：基础算力 + 加赠分开发放（加赠幂等键带 _FIRST_BONUS 后缀）"""
        svc, calls = patched_service
        util = make_util()
        params = _signed_pay_success_params(util)
        import services.subscription_service as real_svc

        def _first_order(order_id):
            return _FakeOrder(order_id=order_id, period_index=1, computing_power=1000)
        svc.SubscriptionOrdersModel.get_by_order_id = staticmethod(_first_order)
        # 签约回调先于支付回调到达：合约已 ACTIVE，且为用户首份成功签约合约
        svc.WxPapayContractsModel.get_by_contract_code = staticmethod(
            lambda code: _FakeContract(status=WxContractStatus.ACTIVE, contract_code=code)
        )
        ok = asyncio.run(real_svc.handle_pay_callback(params))
        assert ok is True
        assert calls["settle"][0]["computing_power"] == 1000
        # 基础算力 2400（抽佣后）与加赠 400 分两笔发放，加赠使用独立幂等键
        assert calls["grant"] == [
            (1, 2400, "4200001234"),
            (1, 400, "4200001234_FIRST_BONUS"),
        ]
        assert calls["bonus_flag"] == ["SUB_1_a"]

    def test_bonus_deferred_until_contract_signed(self, patched_service):
        """支付时合约仍签约中（典型时序）：本次只发基础算力，加赠顺延到签约成功后补发"""
        svc, calls = patched_service
        util = make_util()
        params = _signed_pay_success_params(util)

        def _first_order(order_id):
            return _FakeOrder(order_id=order_id, period_index=1, computing_power=1000)
        svc.SubscriptionOrdersModel.get_by_order_id = staticmethod(_first_order)
        # fixture 默认合约 PENDING → 不加赠
        ok = asyncio.run(svc.handle_pay_callback(params))
        assert ok is True
        assert calls["grant"] == [(1, 2400, "4200001234")]

        # 签约结果（ADD 回调）到达后：签约成功，首份成功签约合约 → 补发加赠
        order = _FakeOrder(order_id="SUB_1_a", period_index=1, computing_power=1000,
                           status=SubscriptionOrderStatus.PAID, transaction_id="4200001234")
        svc.WxPapayContractsModel.get_by_contract_code = staticmethod(
            lambda code: _FakeContract(status=WxContractStatus.ACTIVE, contract_code=code)
        )
        bonus_ok = asyncio.run(svc._grant_first_period_bonus(order))
        assert bonus_ok is True
        assert calls["grant"][-1] == (1, 400, "4200001234_FIRST_BONUS")

    def test_paid_but_not_signed_no_bonus(self, patched_service):
        """只付款但签约未生效（订阅被关闭）：合约非 ACTIVE，永远不发首订加赠"""
        svc, calls = patched_service
        order = _FakeOrder(period_index=1, computing_power=1000,
                           status=SubscriptionOrderStatus.PAID, transaction_id="4200001234")
        # 查询微信确认签约不存在后已终止合约
        svc.WxPapayContractsModel.get_by_contract_code = staticmethod(
            lambda code: _FakeContract(status=WxContractStatus.TERMINATED, contract_code=code)
        )
        bonus_ok = asyncio.run(svc._grant_first_period_bonus(order))
        assert bonus_ok is True  # 无需发放（非失败）
        assert calls["grant"] == []
        assert calls["bonus_flag"] == []

    def test_resubscribe_after_signed_contract_no_bonus(self, patched_service):
        """已有历史成功签约合约（老用户重新订阅）：首份成功签约判定不通过，不加赠"""
        svc, calls = patched_service
        order = _FakeOrder(period_index=1, computing_power=1000,
                           status=SubscriptionOrderStatus.PAID, transaction_id="4200001234")
        svc.WxPapayContractsModel.get_by_contract_code = staticmethod(
            lambda code: _FakeContract(status=WxContractStatus.ACTIVE, contract_code=code)
        )
        svc.WxPapayContractsModel.exists_signed_contract = staticmethod(
            lambda user_id, exclude_contract_code=None: True
        )
        bonus_ok = asyncio.run(svc._grant_first_period_bonus(order))
        assert bonus_ok is True
        assert calls["grant"] == []
        assert calls["bonus_flag"] == []

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
            staticmethod(lambda code: _FakeContract(status=WxContractStatus.PENDING, contract_code=code)),
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
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "exists_signed_contract",
            staticmethod(lambda user_id, exclude_contract_code=None: False),
        )
        assert svc.get_subscription_status(1) == {
            "subscribed": False, "status": "none", "first_bonus_eligible": True,
        }

    def test_none_after_historical_signed_contract(self, monkeypatch):
        """老用户（有历史成功签约合约）解约后查询：无合约 → 仍无首订加赠资格"""
        from services import subscription_service as svc
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_latest_by_user",
            staticmethod(lambda user_id: None),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "exists_signed_contract",
            staticmethod(lambda user_id, exclude_contract_code=None: True),
        )
        assert svc.get_subscription_status(1)["first_bonus_eligible"] is False

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
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "exists_signed_contract",
            staticmethod(lambda user_id, exclude_contract_code=None: True),
        )
        status = svc.get_subscription_status(1)
        assert status["subscribed"] is True
        assert status["status"] == "active"
        assert status["next_deduct_date"] == C.current_period_end.date().isoformat()
        # 生效中用户已有历史已支付订单 → 无首订加赠资格
        assert status["first_bonus_eligible"] is False

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
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "exists_signed_contract",
            staticmethod(lambda user_id, exclude_contract_code=None: True),
        )
        status = svc.get_subscription_status(1)
        assert status["subscribed"] is False
        assert status["status"] == "expired"


# ==================== 套餐升级（无需退订，低→高） ====================

class _FakeContract:
    def __init__(self, **kw):
        self.contract_code = "SUBC_OLD"
        self.contract_id = "WxOLD"
        self.user_id = 1
        self.subscription_plan_id = 101
        self.status = WxContractStatus.ACTIVE
        self.current_period_end = datetime.now() + timedelta(days=10)
        self.__dict__.update(kw)


class TestCreateSignPayOrderUpgrade:
    """生效中用户发起更高套餐签约：放行并记录被替换合约；同档/降级仍拒绝"""

    def _patch_models(self, svc, monkeypatch, existing):
        calls = {"create": [], "terminated": [], "closed": []}
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_active_by_user",
            staticmethod(lambda user_id: existing),
        )
        # 已签约合约列表（去重清理用）：默认与 get_active_by_user 的生效单条一致
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_active_contracts_by_user",
            staticmethod(lambda user_id: (
                [existing] if existing and existing.status == WxContractStatus.ACTIVE else []
            )),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "create",
            staticmethod(lambda **kw: calls.setdefault("contract_created", []).append(kw) or 1),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "mark_terminated",
            staticmethod(lambda code, mode=None, remark=None: calls["terminated"].append(code) or 1),
        )
        monkeypatch.setattr(
            svc.SubscriptionOrdersModel, "get_latest_by_contract",
            staticmethod(lambda code: None),
        )
        monkeypatch.setattr(
            svc.SubscriptionOrdersModel, "create",
            staticmethod(lambda **kw: calls["create"].append(kw) or 1),
        )
        monkeypatch.setattr(
            svc.SubscriptionOrdersModel, "close",
            staticmethod(lambda oid, c=None, m=None: calls["closed"].append(oid) or 1),
        )
        return calls

    def _patch_pay(self, svc, monkeypatch, result=None):
        util = make_util()
        monkeypatch.setattr(svc, "get_papay_util", lambda *a, **kw: util)
        monkeypatch.setattr(
            util, "create_contract_order",
            lambda **kw: result or {
                "return_code": "SUCCESS", "result_code": "SUCCESS",
                "code_url": "weixin://wxpay/abc",
            },
        )
        return util

    def _create(self, svc, plan_id):
        return asyncio.run(svc.create_sign_pay_order(
            user_id=1, subscription_plan_id=plan_id, is_wechat_browser=False,
            openid=None, payment_ip=None, display_name="138****0000",
        ))

    def test_upgrade_allowed_and_records_source(self, monkeypatch):
        from services import subscription_service as svc
        existing = _FakeContract(subscription_plan_id=101)  # 入门版生效中
        calls = self._patch_models(svc, monkeypatch, existing)
        self._patch_pay(svc, monkeypatch)

        result = self._create(svc, 102)  # 升级到标准版
        assert result["upgrade"] is True
        assert result["current_plan"]["plan_id"] == 101
        assert calls["create"][0]["upgrade_from_contract_code"] == "SUBC_OLD"
        assert calls["create"][0]["subscription_plan_id"] == 102
        # 旧合约保持不动，等待支付成功回调再解约
        assert calls["terminated"] == []

    def test_same_or_lower_plan_rejected(self, monkeypatch):
        from services import subscription_service as svc
        existing = _FakeContract(subscription_plan_id=103)  # 专业版生效中
        self._patch_models(svc, monkeypatch, existing)

        with pytest.raises(svc.SubscriptionServiceError):
            self._create(svc, 102)
        with pytest.raises(svc.SubscriptionServiceError):
            self._create(svc, 103)

    def test_upgrade_api_failure_aborts_before_persist(self, monkeypatch):
        """微信签约下单失败时不落库，旧合约不受影响"""
        from services import subscription_service as svc
        existing = _FakeContract(subscription_plan_id=101)
        calls = self._patch_models(svc, monkeypatch, existing)
        self._patch_pay(svc, monkeypatch, result={
            "return_code": "SUCCESS", "result_code": "FAIL", "err_code": "INVALID_REQUEST",
        })

        with pytest.raises(svc.SubscriptionServiceError):
            self._create(svc, 102)
        assert calls["create"] == []


class TestUpgradePayCallback:
    def test_upgrade_settlement_terminates_source_without_bonus(self, patched_service, monkeypatch):
        """升级单支付成功：解约被替换旧合约；不发首期加赠"""
        svc, calls = patched_service

        def _upgrade_order(order_id):
            return _FakeOrder(order_id=order_id, period_index=1, computing_power=1000,
                              upgrade_from_contract_code="SUBC_OLD")
        svc.SubscriptionOrdersModel.get_by_order_id = staticmethod(_upgrade_order)
        terminated = []

        async def fake_terminate(code):
            terminated.append(code)
        monkeypatch.setattr(svc, "_terminate_replaced_contract", fake_terminate)

        ok = asyncio.run(svc.handle_pay_callback(_signed_pay_success_params(make_util())))
        assert ok is True
        assert terminated == ["SUBC_OLD"]
        # 升级单：抽佣后 2400，无首期加赠
        assert calls["grant"] == [(1, 2400, "4200001234")]


class TestUpgradeTerminateReplacedContract:
    def test_local_terminate_then_wechat_api(self, monkeypatch):
        from services import subscription_service as svc
        calls = {"terminated": [], "remark": []}
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_by_contract_code",
            staticmethod(lambda code: _FakeContract(contract_code=code)),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "mark_terminated",
            staticmethod(lambda code, mode=None, remark=None: calls["terminated"].append((code, remark)) or 1),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "update_termination_remark",
            staticmethod(lambda code, remark: calls["remark"].append((code, remark)) or 1),
        )
        util = make_util()
        monkeypatch.setattr(svc, "get_papay_util", lambda *a, **kw: util)
        monkeypatch.setattr(
            util, "delete_contract",
            lambda **kw: {"return_code": "SUCCESS", "result_code": "SUCCESS"},
        )
        asyncio.run(svc._terminate_replaced_contract("SUBC_OLD"))
        assert calls["terminated"][0][1] == svc.SubscriptionConstants.UPGRADE_TERMINATE_REMARK
        assert calls["remark"] == [("SUBC_OLD", svc.SubscriptionConstants.UPGRADE_TERMINATE_REMARK_CONFIRMED)]

    def test_wechat_api_failure_keeps_pending_confirm(self, monkeypatch):
        from services import subscription_service as svc
        calls = {"remark": []}
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_by_contract_code",
            staticmethod(lambda code: _FakeContract(contract_code=code)),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "mark_terminated",
            staticmethod(lambda code, mode=None, remark=None: 1),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "update_termination_remark",
            staticmethod(lambda code, remark: calls["remark"].append((code, remark)) or 1),
        )
        util = make_util()
        monkeypatch.setattr(svc, "get_papay_util", lambda *a, **kw: util)
        monkeypatch.setattr(
            util, "delete_contract",
            lambda **kw: {"return_code": "SUCCESS", "result_code": "FAIL", "err_code": "SYSTEMERROR"},
        )
        asyncio.run(svc._terminate_replaced_contract("SUBC_OLD"))
        # API 失败：备注保持待确认，由补偿任务重试
        assert calls["remark"] == []


class TestUpgradeStatus:
    def test_upgrading_view(self, monkeypatch):
        from services import subscription_service as svc
        pending = _FakeContract(status=WxContractStatus.PENDING, subscription_plan_id=103,
                                contract_code="SUBC_NEW", current_period_end=None)
        active_old = _FakeContract(subscription_plan_id=101)
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_latest_by_user",
            staticmethod(lambda uid: pending),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_active_signed_by_user",
            staticmethod(lambda uid: active_old),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "exists_signed_contract",
            staticmethod(lambda user_id, exclude_contract_code=None: True),
        )
        status = svc.get_subscription_status(1)
        assert status["status"] == "upgrading"
        assert status["subscribed"] is True
        assert status["plan"]["plan_id"] == 101
        assert status["pending_plan"]["plan_id"] == 103
        assert status["next_deduct_date"] == active_old.current_period_end.date().isoformat()

    def test_pending_without_active_stays_signing(self, monkeypatch):
        from services import subscription_service as svc
        pending = _FakeContract(status=WxContractStatus.PENDING, subscription_plan_id=103,
                                contract_code="SUBC_NEW", current_period_end=None)
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_latest_by_user",
            staticmethod(lambda uid: pending),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_active_signed_by_user",
            staticmethod(lambda uid: None),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "exists_signed_contract",
            staticmethod(lambda user_id, exclude_contract_code=None: False),
        )
        status = svc.get_subscription_status(1)
        assert status["status"] == "signing"
        assert status["subscribed"] is False

    def test_terminated_sign_not_effective_flagged(self, monkeypatch):
        """支付成功但签约未生效的已终止合约：返回 sign_not_effective（区别于用户主动解约）"""
        from services import subscription_service as svc
        terminated = _FakeContract(
            status=WxContractStatus.TERMINATED, subscription_plan_id=101,
            termination_remark=svc.SubscriptionConstants.SIGN_FAILED_TERMINATE_REMARK,
            current_period_end=datetime.now() + timedelta(days=20),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_latest_by_user",
            staticmethod(lambda uid: terminated),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "exists_signed_contract",
            staticmethod(lambda user_id, exclude_contract_code=None: True),
        )
        status = svc.get_subscription_status(1)
        assert status["status"] == "terminated"
        assert status["subscribed"] is True  # 单期已付权益保留至周期结束
        assert status["sign_not_effective"] is True

    def test_terminated_user_cancel_not_flagged(self, monkeypatch):
        """用户主动解约：不返回 sign_not_effective"""
        from services import subscription_service as svc
        terminated = _FakeContract(
            status=WxContractStatus.TERMINATED, subscription_plan_id=101,
            termination_remark="用户主动取消订阅",
            current_period_end=datetime.now() + timedelta(days=20),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_latest_by_user",
            staticmethod(lambda uid: terminated),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "exists_signed_contract",
            staticmethod(lambda user_id, exclude_contract_code=None: True),
        )
        status = svc.get_subscription_status(1)
        assert status["status"] == "terminated"
        assert "sign_not_effective" not in status


# ==================== 支付成功但签约通知未到的补偿查询 ====================

class TestReconcilePendingSigns:
    """首期已支付但合约仍签约中：按微信 querycontract 结果收尾（补激活/终止/等待）"""

    def _setup(self, monkeypatch, query_result):
        from services import subscription_service as svc
        contract = _FakeContract(
            status=WxContractStatus.PENDING, contract_code="SUBC_NEW",
            plan_template_id="223101", openid="oX1",
        )
        calls = {"signed": [], "terminated": []}
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_paid_pending_signs",
            staticmethod(lambda grace, limit=50: [contract]),
        )
        monkeypatch.setattr(
            svc.SubscriptionOrdersModel, "get_latest_by_contract",
            staticmethod(lambda contract_code: None),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "mark_signed",
            staticmethod(lambda code, cid, openid=None: calls["signed"].append((code, cid, openid)) or 1),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "mark_terminated",
            staticmethod(lambda code, mode=None, remark=None: calls["terminated"].append((code, remark)) or 1),
        )
        util = make_util()
        monkeypatch.setattr(svc, "get_papay_util", lambda *a, **kw: util)
        monkeypatch.setattr(util, "query_contract", lambda **kw: query_result)
        return svc, calls

    def test_signed_at_wechat_activates(self, monkeypatch):
        """微信侧已签约（ADD 回调丢失）：补 mark_signed 激活"""
        svc, calls = self._setup(monkeypatch, {
            "return_code": "SUCCESS", "result_code": "SUCCESS",
            "contract_state": "0", "contract_id": "20260917WX", "openid": "oX1",
        })
        asyncio.run(svc._reconcile_pending_signs())
        assert calls["signed"] == [("SUBC_NEW", "20260917WX", "oX1")]
        assert calls["terminated"] == []

    def test_unsigned_terminates_with_remark(self, monkeypatch):
        """微信侧未签约（contract_state=1）：终止合约留痕，不激活"""
        svc, calls = self._setup(monkeypatch, {
            "return_code": "SUCCESS", "result_code": "SUCCESS", "contract_state": "1",
        })
        asyncio.run(svc._reconcile_pending_signs())
        assert calls["signed"] == []
        assert len(calls["terminated"]) == 1
        # 备注为约定常量：状态视图据此区分"签约未生效"，单期已付权益保留、不退款不回收算力
        assert calls["terminated"][0][1] == svc.SubscriptionConstants.SIGN_FAILED_TERMINATE_REMARK

    def test_not_found_terminates_with_remark(self, monkeypatch):
        """微信侧查无记录（err_code=-25 RESULT NULL）：同样视为签约未生效，终止留痕"""
        svc, calls = self._setup(monkeypatch, {
            "return_code": "SUCCESS", "result_code": "FAIL",
            "err_code": "-25", "err_code_des": "RESULT NULL",
        })
        asyncio.run(svc._reconcile_pending_signs())
        assert calls["signed"] == []
        assert len(calls["terminated"]) == 1

    def test_signing_in_progress_waits(self, monkeypatch):
        """微信侧签约进行中（contract_state=9）：不动，等下一周期"""
        svc, calls = self._setup(monkeypatch, {
            "return_code": "SUCCESS", "result_code": "SUCCESS", "contract_state": "9",
        })
        asyncio.run(svc._reconcile_pending_signs())
        assert calls["signed"] == [] and calls["terminated"] == []

    def test_query_error_waits(self, monkeypatch):
        """查询接口异常（SYSTEMERROR）：不误终止，等下一周期重试"""
        svc, calls = self._setup(monkeypatch, {
            "return_code": "SUCCESS", "result_code": "FAIL", "err_code": "SYSTEMERROR",
        })
        asyncio.run(svc._reconcile_pending_signs())
        assert calls["signed"] == [] and calls["terminated"] == []

    def test_signed_without_contract_id_skips(self, monkeypatch):
        """已签约但响应缺 contract_id：不激活（无协议ID无法续期），等下一周期"""
        svc, calls = self._setup(monkeypatch, {
            "return_code": "SUCCESS", "result_code": "SUCCESS",
            "contract_state": "0", "contract_id": "",
        })
        asyncio.run(svc._reconcile_pending_signs())
        assert calls["signed"] == [] and calls["terminated"] == []


# ==================== 首订加赠发放入口与幂等 ====================

class TestFirstPeriodBonusEntryPoints:
    """加赠经"签约结果回调（ADD）"入口补发、重复触发幂等、补偿重试补发"""

    @staticmethod
    def _activate_contract(svc):
        svc.WxPapayContractsModel.get_by_contract_code = staticmethod(
            lambda code: _FakeContract(status=WxContractStatus.ACTIVE, contract_code=code)
        )

    def _signed_add_params(self, util):
        params = {
            "return_code": "SUCCESS", "result_code": "SUCCESS",
            "mch_id": "1900000109", "contract_code": "SUBC1",
            "openid": "oX1", "change_type": "ADD",
            "operate_time": "2026-09-17 10:00:00",
            "contract_id": "Wx154abc", "request_serial": "100",
        }
        params["sign"] = util._sign_v2(params)
        return params

    def test_add_callback_grants_pending_bonus(self, patched_service):
        """ADD 回调到达（支付已先行结算基础算力）：经回调入口补发首订加赠"""
        svc, calls = patched_service
        self._activate_contract(svc)
        order = _FakeOrder(order_id="SUB_1_a", period_index=1, computing_power=1000,
                           status=SubscriptionOrderStatus.PAID, transaction_id="4200001234")
        svc.SubscriptionOrdersModel.get_latest_by_contract = staticmethod(lambda code: order)

        ok = asyncio.run(svc.handle_contract_callback(self._signed_add_params(make_util())))
        assert ok is True
        assert calls["mark_signed"] == [("SUBC1", "Wx154abc")]
        # 仅补发加赠（基础算力已由支付回调发放）
        assert calls["grant"] == [(1, 400, "4200001234_FIRST_BONUS")]
        assert calls["bonus_flag"] == ["SUB_1_a"]

    def test_add_callback_before_pay_settles_bonus_later(self, patched_service):
        """ADD 回调先于支付回调：订单未支付不加赠；支付结算时合约已 ACTIVE 再发"""
        svc, calls = patched_service
        self._activate_contract(svc)
        unpaid = _FakeOrder(order_id="SUB_1_a", period_index=1, computing_power=1000,
                            status=SubscriptionOrderStatus.PENDING_PAY, transaction_id=None)
        svc.SubscriptionOrdersModel.get_latest_by_contract = staticmethod(lambda code: unpaid)
        ok = asyncio.run(svc.handle_contract_callback(self._signed_add_params(make_util())))
        assert ok is True
        assert calls["grant"] == []  # 订单未支付，顺延

        # 支付回调随后到达：合约已 ACTIVE → 结算时一并发放加赠
        svc.SubscriptionOrdersModel.get_by_order_id = staticmethod(
            lambda order_id: _FakeOrder(order_id=order_id, period_index=1, computing_power=1000)
        )
        ok = asyncio.run(svc.handle_pay_callback(_signed_pay_success_params(make_util())))
        assert ok is True
        assert calls["grant"] == [(1, 2400, "4200001234"), (1, 400, "4200001234_FIRST_BONUS")]

    def test_bonus_double_trigger_grants_once(self, patched_service):
        """支付结算与 ADD 回调重复触发（或事件重投）：加赠只发一次（first_bonus_granted 幂等）"""
        svc, calls = patched_service
        self._activate_contract(svc)
        order = _FakeOrder(period_index=1, computing_power=1000,
                           status=SubscriptionOrderStatus.PAID, transaction_id="4200001234")
        assert asyncio.run(svc._grant_first_period_bonus(order)) is True
        # 模拟已落库后再触发（迟到的重复事件/补偿重试）
        order.first_bonus_granted = 1
        assert asyncio.run(svc._grant_first_period_bonus(order)) is True
        assert calls["grant"] == [(1, 400, "4200001234_FIRST_BONUS")]
        assert calls["bonus_flag"] == ["SUB_1_a"]

    def test_settlement_retry_grants_missed_bonus(self, patched_service):
        """补偿重试：基础算力重发成功后，补发首次失败漏掉的首订加赠"""
        svc, calls = patched_service
        self._activate_contract(svc)
        order = _FakeOrder(period_index=1, computing_power=1000,
                           status=SubscriptionOrderStatus.PAID, transaction_id="4200001234")
        svc.SubscriptionOrdersModel.get_grant_pending_orders = staticmethod(lambda limit=50: [order])
        asyncio.run(svc.process_settlement_retry())
        assert calls["grant"] == [
            (1, 1000, "4200001234"),           # 补偿重试：按订单基础算力重发
            (1, 400, "4200001234_FIRST_BONUS"),  # 顺带补发漏掉的加赠
        ]


class TestSingleActiveContractGuarantee:
    """"系统与微信侧都只保留一个生效订阅"：新约生效清理其它签约/残留复活/兜底去重"""

    @staticmethod
    def _contracts_map(monkeypatch, svc, contracts):
        """get_by_contract_code 按合约号分流返回（模拟真实库的当前状态）"""
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_by_contract_code",
            staticmethod(lambda code: contracts.get(code)),
        )

    @staticmethod
    def _record_termination(monkeypatch, svc, calls):
        """mark_terminated 记录 (code, remark)，delete_contract 记录调用并返回成功"""
        calls.setdefault("terminated", [])
        calls.setdefault("remark", [])
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "mark_terminated",
            staticmethod(lambda code, mode=None, remark=None: calls["terminated"].append((code, remark)) or 1),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "update_termination_remark",
            staticmethod(lambda code, remark: calls["remark"].append((code, remark)) or 1),
        )
        util = make_util()
        monkeypatch.setattr(svc, "get_papay_util", lambda *a, **kw: util)
        monkeypatch.setattr(
            util, "delete_contract",
            lambda **kw: {"return_code": "SUCCESS", "result_code": "SUCCESS"},
        )
        return util

    def _signed_add(self, util, code):
        params = {
            "return_code": "SUCCESS", "result_code": "SUCCESS",
            "mch_id": "1900000109", "contract_code": code,
            "openid": "oX1", "change_type": "ADD",
            "operate_time": "2026-09-17 10:00:00",
            "contract_id": "Wx154abc", "request_serial": "100",
        }
        params["sign"] = util._sign_v2(params)
        return params

    def test_add_callback_terminates_other_active_contracts(self, patched_service, monkeypatch):
        """新约 ADD 生效：解约用户其它已签约合约（微信侧只保留一个订阅）"""
        svc, calls = patched_service
        new = _FakeContract(status=WxContractStatus.PENDING, contract_code="SUBC_NEW", user_id=1)
        old = _FakeContract(status=WxContractStatus.ACTIVE, contract_code="SUBC_OLD", user_id=1)
        contracts = {"SUBC_NEW": new, "SUBC_OLD": old}
        self._contracts_map(monkeypatch, svc, contracts)
        self._record_termination(monkeypatch, svc, calls)
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_active_contracts_by_user",
            staticmethod(lambda uid: [new, old]),
        )

        ok = asyncio.run(svc.handle_contract_callback(self._signed_add(make_util(), "SUBC_NEW")))
        assert ok is True
        assert calls["mark_signed"] == [("SUBC_NEW", "Wx154abc")]
        # 旧约被解约（本地终止 + 微信 delete_contract），新约保留
        assert calls["terminated"] == [("SUBC_OLD", svc.SubscriptionConstants.DEDUP_TERMINATE_REMARK)]
        assert calls["remark"] == [("SUBC_OLD", f"{svc.SubscriptionConstants.DEDUP_TERMINATE_REMARK}(微信侧已解除)")]

    def test_add_callback_resurrected_contract_terminated_again(self, patched_service, monkeypatch):
        """已终止合约收到迟到 ADD（微信侧签约实际已生效）：若用户已有其它生效签约，复活后立即解约自己"""
        svc, calls = patched_service
        state = {"status": WxContractStatus.TERMINATED}
        res = _FakeContract(status=WxContractStatus.TERMINATED, contract_code="SUBC_RES", user_id=1)

        def _get(code):
            res.status = state["status"]
            return res

        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_by_contract_code", staticmethod(lambda code: _get(code)),
        )

        def _mark_signed(code, cid, openid=None):
            state["status"] = WxContractStatus.ACTIVE  # 模拟落库复活
            return 1
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "mark_signed", staticmethod(_mark_signed),
        )
        other = _FakeContract(status=WxContractStatus.ACTIVE, contract_code="SUBC_B", user_id=1)
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_active_contracts_by_user",
            staticmethod(lambda uid: [other]),
        )
        self._record_termination(monkeypatch, svc, calls)

        ok = asyncio.run(svc.handle_contract_callback(self._signed_add(make_util(), "SUBC_RES")))
        assert ok is True
        # 复活后发现有其它生效签约：解约自己，终态 terminated
        assert calls["terminated"] == [("SUBC_RES", svc.SubscriptionConstants.DEDUP_TERMINATE_REMARK)]

    def test_add_callback_resurrected_contract_kept_when_no_others(self, patched_service, monkeypatch):
        """已终止合约收到迟到 ADD 且用户无其它生效签约：保留签约（误终止自愈）"""
        svc, calls = patched_service
        res = _FakeContract(status=WxContractStatus.TERMINATED, contract_code="SUBC_RES", user_id=1)
        self._contracts_map(monkeypatch, svc, {"SUBC_RES": res})
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_active_contracts_by_user",
            staticmethod(lambda uid: []),
        )
        self._record_termination(monkeypatch, svc, calls)

        ok = asyncio.run(svc.handle_contract_callback(self._signed_add(make_util(), "SUBC_RES")))
        assert ok is True
        assert calls["mark_signed"] == [("SUBC_RES", "Wx154abc")]
        assert calls["terminated"] == []

    def test_dedup_task_keeps_latest_only(self, patched_service, monkeypatch):
        """兜底调度：同一用户多条已签约合约，保留最新一条，解约其余"""
        svc, calls = patched_service
        latest = _FakeContract(status=WxContractStatus.ACTIVE, contract_code="SUBC_LATEST", user_id=1)
        old1 = _FakeContract(status=WxContractStatus.ACTIVE, contract_code="SUBC_OLD1", user_id=1)
        old2 = _FakeContract(status=WxContractStatus.ACTIVE, contract_code="SUBC_OLD2", user_id=1)
        self._contracts_map(monkeypatch, svc, {
            "SUBC_LATEST": latest, "SUBC_OLD1": old1, "SUBC_OLD2": old2,
        })
        self._record_termination(monkeypatch, svc, calls)
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_users_with_multiple_active_contracts",
            staticmethod(lambda limit=100: [1]),
        )
        # 返回列表不含 keep 自身以外的排除逻辑在 _terminate_other_contracts；这里直接给全部
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_active_contracts_by_user",
            staticmethod(lambda uid: [latest, old1, old2]),
        )

        asyncio.run(svc._dedup_signed_contracts())
        assert calls["terminated"] == [
            ("SUBC_OLD1", svc.SubscriptionConstants.DEDUP_TERMINATE_REMARK),
            ("SUBC_OLD2", svc.SubscriptionConstants.DEDUP_TERMINATE_REMARK),
        ]

    def test_create_sign_pay_order_clears_multiple_actives(self, patched_service, monkeypatch):
        """重新发起订阅时若已有多条生效签约（残留）：先清理只留最新，再走升级逻辑"""
        svc, calls = patched_service
        latest = _FakeContract(status=WxContractStatus.ACTIVE, contract_code="SUBC_LATEST",
                               user_id=1, subscription_plan_id=101)
        stale = _FakeContract(status=WxContractStatus.ACTIVE, contract_code="SUBC_STALE",
                              user_id=1, subscription_plan_id=101)
        self._contracts_map(monkeypatch, svc, {"SUBC_LATEST": latest, "SUBC_STALE": stale})
        self._record_termination(monkeypatch, svc, calls)
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_active_contracts_by_user",
            staticmethod(lambda uid: [latest, stale]),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_active_by_user",
            staticmethod(lambda uid: latest),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "create",
            staticmethod(lambda **kw: calls.setdefault("contract_created", []).append(kw) or 1),
        )
        monkeypatch.setattr(
            svc.SubscriptionOrdersModel, "create",
            staticmethod(lambda **kw: calls.setdefault("order_created", []).append(kw) or 1),
        )
        monkeypatch.setattr(
            svc.SubscriptionOrdersModel, "get_latest_by_contract",
            staticmethod(lambda code: None),
        )
        monkeypatch.setattr(
            util := make_util(), "create_contract_order",
            lambda **kw: {"return_code": "SUCCESS", "result_code": "SUCCESS",
                          "code_url": "weixin://wxpay/abc"},
        )
        monkeypatch.setattr(svc, "get_papay_util", lambda *a, **kw: util)

        result = asyncio.run(svc.create_sign_pay_order(
            user_id=1, subscription_plan_id=102, is_wechat_browser=False,
            openid=None, payment_ip=None, display_name="138****0000",
        ))
        # 残留旧约先被清理，新单以最新一条为升级来源
        assert calls["terminated"] == [("SUBC_STALE", svc.SubscriptionConstants.DEDUP_TERMINATE_REMARK)]
        assert result["upgrade"] is True
        assert calls["order_created"][0]["upgrade_from_contract_code"] == "SUBC_LATEST"

    def test_reconcile_signed_terminates_other_contracts(self, patched_service, monkeypatch):
        """对账自愈签约成功（ADD 丢失）：同样清理用户其它已签约合约"""
        svc, calls = patched_service
        pending_contract = _FakeContract(status=WxContractStatus.PENDING, contract_code="SUBC_NEW",
                                         user_id=1, plan_template_id="tpl_1", openid="oX1")
        old = _FakeContract(status=WxContractStatus.ACTIVE, contract_code="SUBC_OLD", user_id=1)
        self._contracts_map(monkeypatch, svc, {"SUBC_NEW": pending_contract, "SUBC_OLD": old})
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_paid_pending_signs",
            staticmethod(lambda grace_minutes, limit=50: [pending_contract]),
        )
        monkeypatch.setattr(
            svc.WxPapayContractsModel, "get_active_contracts_by_user",
            staticmethod(lambda uid: [old]),
        )
        util = self._record_termination(monkeypatch, svc, calls)
        monkeypatch.setattr(
            util, "query_contract",
            lambda **kw: {"return_code": "SUCCESS", "result_code": "SUCCESS",
                          "contract_state": "0", "contract_id": "Wx154abc"},
        )

        asyncio.run(svc._reconcile_pending_signs())
        assert calls["terminated"] == [("SUBC_OLD", svc.SubscriptionConstants.DEDUP_TERMINATE_REMARK)]
