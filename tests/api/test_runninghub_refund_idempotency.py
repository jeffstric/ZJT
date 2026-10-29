"""runninghub-status FAILED 分支退费幂等测试（审计 BUG-R4-C3-H1）。

GET /api/runninghub-status/{id} 的 FAILED 分支曾每次轮询生成新 uuid4 作退费
流水号——绕过 perseids 交易号去重，任务属主反复轮询同一失败任务即可无限
重复退费（实测 N 次轮询 = N 倍任务价退费；后台调度器退费一次后前端一次
轮询还会再叠一次）。修复：对齐后台退费路径（task/visual_task.py）的幂等
模式——is_already_refunded 预检 + refund-{原扣费流水号} 派生流水号。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


def _task_record():
    return SimpleNamespace(
        user_id=1,
        type=1,
        transaction_id="charge-abc-123",  # 提交时的扣费流水号
        duration=None,
        implementation=None,
    )


@pytest.fixture
def env(monkeypatch):
    import server as server_mod

    state = {
        "credited": [],          # calculate_computing_power(increase) 收到的流水号
        "refund_txn_exists": False,  # 第一次退费落账后置 True（模拟下次轮询时账本已有记录）
    }

    monkeypatch.setattr(
        server_mod.AIToolsModel, "get_by_project_id",
        staticmethod(lambda pid: _task_record()),
    )
    monkeypatch.setattr(
        server_mod.AIToolsModel, "update_by_project_id",
        staticmethod(lambda **kw: 1),
    )
    monkeypatch.setattr(
        server_mod.RunningHubClient, "check_status",
        staticmethod(lambda pid: server_mod.TaskStatus.FAILED),
    )

    from model.computing_power_log import ComputingPowerLogModel

    def _exists(txn):
        return state["refund_txn_exists"]

    monkeypatch.setattr(
        ComputingPowerLogModel, "check_transaction_exists",
        staticmethod(_exists),
    )

    async def _perseids(endpoint=None, method=None, headers=None, data=None):
        if endpoint == "user/get_user_id_by_auth_token":
            return True, "ok", {"user_id": 1}
        if endpoint == "user/calculate_computing_power":
            state["credited"].append(data["transaction_id"])
            return True, "ok", {}
        return True, "ok", {}

    monkeypatch.setattr(server_mod, "async_make_perseids_request", _perseids)

    from model.user_tokens import UserTokensModel
    monkeypatch.setattr(
        UserTokensModel, "get_user_id_by_token",
        staticmethod(lambda token: 1 if token == "tk" else None),
    )
    return state, server_mod


def _poll(server_mod):
    from fastapi.testclient import TestClient
    client = TestClient(server_mod.app)
    return client.get(
        "/api/runninghub-status/proj-1",
        headers={"Authorization": "Bearer tk"},
    )


def test_first_failed_poll_refunds_once_with_derived_txn(env):
    """首次轮询 FAILED：退费一次，流水号由扣费流水号派生（幂等键）"""
    state, server_mod = env
    resp = _poll(server_mod)
    assert resp.status_code == 200
    assert state["credited"] == ["refund-charge-abc-123"]


def test_repeat_poll_after_refund_skips_credit(env):
    """退费落账后的重复轮询：不再退费（曾可无限重放薅算力）"""
    state, server_mod = env
    _poll(server_mod)                 # 第一次：退费
    state["refund_txn_exists"] = True  # 模拟账本已有 refund-charge-abc-123
    resp = _poll(server_mod)          # 第二次轮询同一失败任务
    assert resp.status_code == 200
    assert resp.json()["status"] == "FAILED"
    assert state["credited"] == ["refund-charge-abc-123"], "重复轮询不得再次退费"
