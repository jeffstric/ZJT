"""微信支付 V3 充值回调错误路径测试（审计 BUG-R2-S2-A2-H4 吞单修复）。

回调对微信的响应是"已履约"的证明：200/204 = 停止全部重试。曾有三条
错误路径把"已收款未入账"的订单变成永久吞单：
1. 取用户 token 失败时裸 `return False` → FastAPI 序列化为 200 body `false`
   → 微信停止重试，订单永远 status=0；
2. `update_paid` 在入账前执行 → status=1 墓碑让后续重试命中早退分支
   直接应答 SUCCESS，但算力从未发放；
3. 入账调用 success=False 被无视 → 无条件应答 SUCCESS。

修复后约定：任何未入账的失败都应答 5xx 让微信按 15s..6h 计划重试；
update_paid 移到入账成功（或幂等重放"该交易已处理"）之后。
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


class _OrderStub:
    def __init__(self):
        self.order_id = "ORDER_1_ab12cd34"
        self.status = 0
        self.user_id = 1
        self.computing_power = 88
        self.package_id = 1  # 非首充包（首充=5，走独立分支）
        self.price = 9.9


def _fake_request(body: bytes):
    return SimpleNamespace(
        headers={},
        body=lambda: asyncio.sleep(0, result=body),  # async
    )


def _callback_body(order_id="ORDER_1_ab12cd34", transaction_id="TXN_1"):
    resource = json.dumps(
        {"out_trade_no": order_id, "transaction_id": transaction_id, "trade_state": "SUCCESS"}
    )
    return json.dumps(
        {
            "event_type": "TRANSACTION.SUCCESS",
            "resource": {
                "ciphertext": resource,
                "associated_data": "transaction",
                "nonce": "n" * 12,
            },
        }
    ).encode("utf-8")


@pytest.fixture
def setup(monkeypatch):
    """mock 验签/解密/订单模型，返回可编排各阶段结果的控制器。"""
    import server as server_mod

    state = {
        "token_ok": True,
        "credit_ok": True,
        "credit_message": "",
        "update_paid_calls": [],
    }

    monkeypatch.setattr(
        server_mod.wechat_pay_util, "verify_callback_signature",
        lambda *a, **k: True,
    )

    def _decrypt(nonce, ciphertext, associated_data):
        return ciphertext  # 测试直接把明文 JSON 塞进 ciphertext 字段

    monkeypatch.setattr(
        server_mod.wechat_pay_util, "decrypt_callback_resource", _decrypt
    )

    monkeypatch.setattr(
        server_mod.PaymentOrdersModel, "get_by_order_id",
        staticmethod(lambda oid: _OrderStub()),
    )
    monkeypatch.setattr(
        server_mod.PaymentOrdersModel, "update_paid",
        staticmethod(lambda oid, txn: state["update_paid_calls"].append((oid, txn)) or 1),
    )

    async def _perseids(endpoint=None, method=None, headers=None, data=None):
        if endpoint == "get_auth_token_by_user_id":
            if state["token_ok"]:
                return True, "ok", {"token": "user-token"}
            return False, "服务器内部错误", {}
        if endpoint == "commission/settle":
            return False, "skip", {}
        if endpoint == "user/calculate_computing_power":
            if state["credit_ok"] or state["credit_message"] == "该交易已处理":
                if state["credit_message"] == "该交易已处理":
                    return False, "该交易已处理", {}
                return True, "ok", {}
            return False, state["credit_message"] or "服务器内部错误", {}
        return True, "ok", {}

    monkeypatch.setattr(server_mod, "async_make_perseids_request", _perseids)
    return state, server_mod


def _run(server_mod, body):
    return asyncio.run(server_mod.wechat_payment_callback(_fake_request(body)))


def test_token_failure_answers_5xx_and_keeps_order_open(setup):
    """取 token 失败（用户登出/顶号/DB 抖动）→ 5xx 让微信重试，绝不 200"""
    state, server_mod = setup
    state["token_ok"] = False
    resp = _run(server_mod, _callback_body())
    assert resp.status_code == 500
    assert state["update_paid_calls"] == [], "未入账不得打 status=1 墓碑"


def test_credit_failure_answers_5xx_and_keeps_order_open(setup):
    """入账失败 → 5xx 让微信重试；update_paid 不得先于入账执行"""
    state, server_mod = setup
    state["credit_ok"] = False
    state["credit_message"] = "服务器内部错误"
    resp = _run(server_mod, _callback_body())
    assert resp.status_code == 500
    assert state["update_paid_calls"] == []


def test_credit_success_marks_paid_and_acks(setup):
    """入账成功 → update_paid 落账 + 应答 200 SUCCESS"""
    state, server_mod = setup
    resp = _run(server_mod, _callback_body())
    assert resp.status_code == 200
    assert resp.body == b'{"code":"SUCCESS","message":"OK"}'
    assert state["update_paid_calls"] == [("ORDER_1_ab12cd34", "TXN_1")]


def test_idempotent_replay_marks_paid_and_acks(setup):
    """微信重试命中入账幂等（"该交易已处理"）→ 补落 update_paid + 200"""
    state, server_mod = setup
    state["credit_ok"] = False
    state["credit_message"] = "该交易已处理"
    resp = _run(server_mod, _callback_body())
    assert resp.status_code == 200
    assert state["update_paid_calls"] == [("ORDER_1_ab12cd34", "TXN_1")]
