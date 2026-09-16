"""
渠道佣金阶梯结算回归测试（新价目方案：比例按档位写死，现金佣金）

覆盖：
  - 订阅/直充各档：用户到账 = 固定"抽成后"值；渠道佣金 = 固定渠道金额（现金）
  - 无邀请人：不抽佣、不写账本，用户到账 = 不抽成值
  - 未知档位：不抽佣全额到账（向后兼容）
  - 幂等：同交易号回放历史 granted
  - 渠道未开通佣金资质：用户仍按档位到账，但不产生渠道佣金
  - set_commission_rate 已停用
"""
from decimal import Decimal

import pytest

from enterprise.services import commission_service as cs


class _FakeLog:
    def __init__(self, granted):
        self.granted_computing_power = granted


class _FakeUser:
    def __init__(self, inviter, channel_level=2):
        self.inviter_id = inviter
        self.channel_level = channel_level  # 邀请人的渠道推广等级（>=2 才产生现金佣金）


@pytest.fixture
def commission_env(monkeypatch):
    """隔离 settle 的外部依赖：账本/用户/社区版开关"""
    calls = {"create": []}
    logs = {}

    class _FakeLogModel:
        @staticmethod
        def get_by_transaction_id(txn):
            return logs.get(txn)

        @staticmethod
        def create(**kw):
            calls["create"].append(kw)
            logs[kw["transaction_id"]] = _FakeLog(kw["granted_computing_power"])

    # user2 有邀请人(9，已开通渠道佣金)；user3 无邀请人；user4 有邀请人但未开通渠道
    users = {
        2: _FakeUser(9, 2),
        3: _FakeUser(None, 2),
        4: _FakeUser(9, 0),
        9: _FakeUser(None, 2),  # 邀请人本人
    }

    monkeypatch.setattr(cs, "IS_COMMUNITY_EDITION", False)
    monkeypatch.setattr(cs, "CommissionLogModel", _FakeLogModel)
    monkeypatch.setattr(
        cs, "UsersModel",
        type("UM", (), {"get_by_id": staticmethod(lambda uid: users.get(uid))}),
    )
    return cs, calls


class TestSettleLadder:
    def test_subscription_standard_invited_fixed_values(self, commission_env):
        """订阅标准版（102）：用户到账 = 固定抽成后 808；渠道现金 = 固定 7.60"""
        cs, calls = commission_env
        r = cs.CommissionService.settle(
            invitee_id=2, order_id="SUB_x", transaction_id="T1",
            package_id=102, order_amount=59.9, computing_power=1000,
        )
        assert r["success"] is True
        assert r["granted_computing_power"] == 808
        row = calls["create"][0]
        assert row["commission_amount"] == Decimal("7.60")
        assert row["commission_rate"] == Decimal("0.19")
        assert row["granted_computing_power"] == 808

    def test_direct_trial_invited_fixed_values(self, commission_env):
        """直充体验包（1）：用户到账 = 88；渠道现金 = 1.46（体验包参与抽佣）"""
        cs, calls = commission_env
        r = cs.CommissionService.settle(
            invitee_id=2, order_id="R_x", transaction_id="T2",
            package_id=1, order_amount=9.9, computing_power=88,
        )
        assert r["success"] is True
        assert r["granted_computing_power"] == 88
        row = calls["create"][0]
        assert row["commission_amount"] == Decimal("1.46")
        assert row["commission_rate"] == Decimal("0.30")

    @pytest.mark.parametrize("pid,full,after,cash", [
        (101, 428, 328, "4.28"),
        (102, 1000, 808, "7.60"),
        (103, 2524, 2148, "15.15"),
        (104, 6216, 5598, "24.86"),
        (1, 122, 88, "1.46"),
        (2, 700, 508, "7.56"),
        (3, 1741, 1358, "15.32"),
        (4, 3647, 2988, "26.26"),
    ])
    def test_all_tiers_ladder_table(self, commission_env, monkeypatch, pid, full, after, cash):
        """八个档位的固定值与配置表逐一一致"""
        cs, calls = commission_env
        users = {2: _FakeUser(9, 2), 9: _FakeUser(None, 2)}
        monkeypatch.setattr(
            cs, "UsersModel",
            type("UM", (), {"get_by_id": staticmethod(lambda uid: users.get(uid))}),
        )
        r = cs.CommissionService.settle(
            invitee_id=2, order_id=f"O_{pid}", transaction_id=f"T_{pid}",
            package_id=pid, order_amount=1, computing_power=full,
        )
        assert r["success"] is True
        assert r["granted_computing_power"] == after
        row = calls["create"][-1]
        assert row["commission_amount"] == Decimal(cash)

    def test_no_inviter_full_power_no_log(self, commission_env):
        """无邀请人：不抽佣、不写账本，到账 = 不抽成值"""
        cs, calls = commission_env
        r = cs.CommissionService.settle(
            invitee_id=3, order_id="SUB_y", transaction_id="T3",
            package_id=102, order_amount=59.9, computing_power=1000,
        )
        assert r["success"] is True
        assert r["granted_computing_power"] == 1000
        assert calls["create"] == []

    def test_unknown_package_full_grant_no_commission(self, commission_env):
        """未知/历史套餐：不抽佣全额到账（向后兼容）"""
        cs, calls = commission_env
        r = cs.CommissionService.settle(
            invitee_id=2, order_id="O", transaction_id="T9",
            package_id=999, order_amount=10, computing_power=500,
        )
        assert r["success"] is True
        assert r["granted_computing_power"] == 500
        assert calls["create"] == []

    def test_idempotent_replay(self, commission_env):
        """同交易号重复回调：回放历史 granted，不重复写账本"""
        cs, calls = commission_env
        cs.CommissionService.settle(
            invitee_id=2, order_id="SUB_x", transaction_id="T1",
            package_id=102, order_amount=59.9, computing_power=1000,
        )
        before = len(calls["create"])
        r = cs.CommissionService.settle(
            invitee_id=2, order_id="SUB_x", transaction_id="T1",
            package_id=102, order_amount=59.9, computing_power=1000,
        )
        assert r["granted_computing_power"] == 808
        assert len(calls["create"]) == before

    def test_channel_not_enabled_skips_commission(self, commission_env, monkeypatch):
        """邀请人 channel_level<2：用户仍按档位到账，但不产生渠道佣金"""
        cs, calls = commission_env
        users = {2: _FakeUser(9, 0), 9: _FakeUser(None, 0)}
        monkeypatch.setattr(
            cs, "UsersModel",
            type("UM", (), {"get_by_id": staticmethod(lambda uid: users.get(uid))}),
        )
        r = cs.CommissionService.settle(
            invitee_id=2, order_id="SUB_z", transaction_id="T4",
            package_id=102, order_amount=59.9, computing_power=1000,
        )
        assert r["success"] is True
        assert r["granted_computing_power"] == 1000
        assert calls["create"] == []

    def test_channel_level_invite_only_skips_commission(self, commission_env, monkeypatch):
        """邀请人仅开通推广链接（level=1）：不产生现金佣金"""
        cs, calls = commission_env
        users = {2: _FakeUser(9, 0), 9: _FakeUser(None, 1)}
        monkeypatch.setattr(
            cs, "UsersModel",
            type("UM", (), {"get_by_id": staticmethod(lambda uid: users.get(uid))}),
        )
        r = cs.CommissionService.settle(
            invitee_id=2, order_id="SUB_l1", transaction_id="T_L1",
            package_id=102, order_amount=59.9, computing_power=1000,
        )
        assert r["success"] is True
        assert r["granted_computing_power"] == 1000
        assert calls["create"] == []

    def test_invitee_level_does_not_gate_inviter_commission(self, commission_env):
        """被邀请人未开通佣金不影响邀请人：邀请人 level>=2 仍结算佣金"""
        cs, calls = commission_env
        r = cs.CommissionService.settle(
            invitee_id=4, order_id="SUB_u4", transaction_id="T_U4",
            package_id=102, order_amount=59.9, computing_power=1000,
        )
        assert r["success"] is True
        assert r["granted_computing_power"] == 808
        assert calls["create"][-1]["commission_amount"] == Decimal("7.60")


class TestSetRateDisabled:
    def test_set_rate_disabled(self):
        """比例自调已停用：一律失败且不抛异常"""
        r = cs.CommissionService.set_commission_rate(9, 0.19)
        assert r["success"] is False
        assert "不支持自定义" in r["message"]


class TestChannelLevelHelper:
    def test_commission_enabled_threshold(self):
        from config.constant import ChannelLevel
        assert ChannelLevel.is_commission_enabled(0) is False
        assert ChannelLevel.is_commission_enabled(1) is False
        assert ChannelLevel.is_commission_enabled(2) is True
        assert ChannelLevel.is_commission_enabled(None) is False
        assert ChannelLevel.CUSTOMER_SERVICE_WECHAT == 'jeffstric'
