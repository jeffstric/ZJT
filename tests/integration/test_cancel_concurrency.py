"""
排队任务取消 S0 不变量——真实 MySQL 并发验证（L2 层）

设计文档 docs/video/queued_task_cancel_design.md §8 事故复盘：CAS 参数错序
事故单测全绿但真库全错。因此取消互斥的正确性必须在真实 MySQL（InnoDB
行锁）上验证，mock 单测只能防回归不能证正确。

覆盖（见 docs/video/queued_task_cancel_rebase_test_plan.md 不变量 I1-I4）：
  D 系列（顺序确定性）：谓词逻辑的确定性证明——取消先落库则闸门必 0 行、
    闸门先抢占则取消必 0 行（409）、终态不被过期/超限 FAILED 覆盖。
  R 系列（屏障竞态）：两个线程在同一行上同时发起条件 UPDATE，验证
    「每轮恰好一方成功」的行锁串行化（I1/I2 的竞争窗口实证）。
  I3 系列：退费幂等键（refund-{扣费流水}）DB 层防重复退费。

运行方式（独立库，不触碰 zjt 开发数据）：
  python -m pytest tests/integration/test_cancel_concurrency.py --basetemp=.pytest_tmp/integ -q
  环境变量 CANCEL_TEST_DB（默认 zjt_cancel_test）/ CANCEL_TEST_PORT（默认 13314）。
  MySQL 不可达时整体 skip（不阻塞 CI 单测）。
"""
import os
import sys
import threading
import unittest
from datetime import datetime, timedelta

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---- 指向隔离测试库（必须在任何 model 导入前完成；池懒加载前重置）----
_TEST_PORT = int(os.environ.get("CANCEL_TEST_PORT", "13314"))
_TEST_DB = os.environ.get("CANCEL_TEST_DB", "zjt_cancel_test")

import model.database as _dbmod  # noqa: E402

_dbmod.DB_CONFIG.update(host="127.0.0.1", port=_TEST_PORT, user="root",
                        password="3bTgThWP2xeX", database=_TEST_DB)
_dbmod._pool = None  # 强制下次取池时按测试库配置重建


def _mysql_available() -> bool:
    try:
        import pymysql
        pymysql.connect(host="127.0.0.1", port=_TEST_PORT, user="root",
                        password="3bTgThWP2xeX", database=_TEST_DB, connect_timeout=3)
        return True
    except Exception:
        return False


MYSQL_UP = _mysql_available()
if not MYSQL_UP:
    raise unittest.SkipTest(
        f"MySQL 测试库不可达(port={_TEST_PORT}, db={_TEST_DB})，真库并发测试整体跳过")

from config.constant import (  # noqa: E402
    AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING, AI_TOOL_STATUS_FAILED,
    AI_TOOL_STATUS_SYNC_QUEUED, AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
    AI_TOOL_STATUS_WAITING_BEFORE_FINISH, AI_TOOL_STATUS_DOWNLOADING,
    AI_TOOL_STATUS_CANCELLED, AI_TOOL_CANCELLABLE_STATUSES,
    AI_TOOL_ACTIVE_STATUSES,
)
from model.ai_tools import AIToolsModel  # noqa: E402
from model.database import execute_query, execute_update  # noqa: E402

_NEXT_ID = [None]


def _next_id() -> int:
    """测试 id 从 MAX(id)+1 起跳，支持重复运行不撞主键。"""
    if _NEXT_ID[0] is None:
        rows = execute_query("SELECT COALESCE(MAX(id), 9000000) AS m FROM ai_tools",
                             fetch_one=True)
        _NEXT_ID[0] = int(rows["m"]) + 1
    _NEXT_ID[0] += 1
    return _NEXT_ID[0]


def _new_ai_tool(status=AI_TOOL_STATUS_PENDING, **fields) -> int:
    """在测试库插入一条 ai_tools 并返回 id（自增段避开开发数据）。"""
    row_id = _next_id()
    cols = {"id": row_id, "type": 5, "status": status, "prompt": "s0-test",
            "user_id": None, "create_time": datetime.now(), "update_time": datetime.now()}
    cols.update(fields)
    placeholders = ", ".join(["%s"] * len(cols))
    execute_update(
        f"INSERT INTO ai_tools ({', '.join(cols)}) VALUES ({placeholders})",
        tuple(cols.values()))
    return row_id


def _get_status(row_id: int):
    row = execute_query("SELECT status FROM ai_tools WHERE id = %s", (row_id,),
                        fetch_one=True)
    return row["status"] if row else None


def _cancel(row_id: int) -> int:
    """取消侧条件更新（与 server.py cancel 接口同一原语）。"""
    return AIToolsModel.transition_status(
        row_id, list(AI_TOOL_CANCELLABLE_STATUSES), AI_TOOL_STATUS_CANCELLED,
        message="任务已被用户取消", completed_time=datetime.now())


def _gate(row_id: int, frm, to) -> int:
    """调度器侧提交闸门（与 visual_task 三处闸门同一原语）。"""
    return AIToolsModel.transition_status(row_id, [frm], to)


class TestSequentialDeterminism(unittest.TestCase):
    """D 系列：谓词逻辑确定性（§8 参数错序事故的真库复现防线——
    该事故下 D1/D2 的行永远不会翻转，测试立即失败）。"""

    def test_d1_cancel_first_then_submit_gate_never_wins(self):
        """I1：取消先落库 → 主提交闸门 0→1 必 0 行，任务停在 CANCELLED。"""
        rid = _new_ai_tool(AI_TOOL_STATUS_PENDING)
        self.assertEqual(_cancel(rid), 1)
        self.assertEqual(_gate(rid, AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING), 0)
        self.assertEqual(_get_status(rid), AI_TOOL_STATUS_CANCELLED)

    def test_d2_gate_first_then_cancel_rejected(self):
        """I2：闸门先抢占 PROCESSING → 取消必 0 行（接口 409，不退费）。"""
        rid = _new_ai_tool(AI_TOOL_STATUS_PENDING)
        self.assertEqual(_gate(rid, AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING), 1)
        self.assertEqual(_cancel(rid), 0)
        self.assertEqual(_get_status(rid), AI_TOOL_STATUS_PROCESSING)

    def test_d3_cancel_during_param_prepare_blocks_completion(self):
        """预处理中取消（4 可取消）→ 完成推进 4→0 必 0 行，不复活。"""
        rid = _new_ai_tool(AI_TOOL_STATUS_WAITING_PARAM_PREPARE)
        self.assertEqual(_cancel(rid), 1)
        self.assertEqual(_gate(rid, AI_TOOL_STATUS_WAITING_PARAM_PREPARE, AI_TOOL_STATUS_PENDING), 0)
        self.assertEqual(_get_status(rid), AI_TOOL_STATUS_CANCELLED)

    def test_d4_cancel_in_sync_pool_blocks_worker_gate(self):
        """同步池排队中取消（3 可取消）→ worker 闸门 3→1 必 0 行，不调上游。"""
        rid = _new_ai_tool(AI_TOOL_STATUS_SYNC_QUEUED)
        self.assertEqual(_cancel(rid), 1)
        self.assertEqual(_gate(rid, AI_TOOL_STATUS_SYNC_QUEUED, AI_TOOL_STATUS_PROCESSING), 0)
        self.assertEqual(_get_status(rid), AI_TOOL_STATUS_CANCELLED)

    def test_d5_double_cancel_only_first_wins(self):
        """I3 前置：重复取消只有第一次 affected=1（第二次 409，不会二次退费）。"""
        rid = _new_ai_tool(AI_TOOL_STATUS_PENDING)
        self.assertEqual(_cancel(rid), 1)
        self.assertEqual(_cancel(rid), 0)

    def test_d6_terminal_cancel_not_overwritten_by_failure_writes(self):
        """C6/I4：过期/超限写 FAILED（条件更新 ACTIVE 集合）不覆盖 CANCELLED。"""
        rid = _new_ai_tool(AI_TOOL_STATUS_CANCELLED)
        affected = AIToolsModel.transition_status(
            rid, list(AI_TOOL_ACTIVE_STATUSES), AI_TOOL_STATUS_FAILED,
            message="任务已过期", completed_time=datetime.now())
        self.assertEqual(affected, 0)
        self.assertEqual(_get_status(rid), AI_TOOL_STATUS_CANCELLED)

    def test_d7_downloading_and_before_finish_not_cancellable(self):
        """设计内：DOWNLOADING / WAITING_BEFORE_FINISH 不可取消（上游成本已发生）。"""
        rid1 = _new_ai_tool(AI_TOOL_STATUS_DOWNLOADING)
        self.assertEqual(_cancel(rid1), 0)
        self.assertEqual(_get_status(rid1), AI_TOOL_STATUS_DOWNLOADING)
        rid2 = _new_ai_tool(AI_TOOL_STATUS_WAITING_BEFORE_FINISH)
        self.assertEqual(_cancel(rid2), 0)

    def test_d7b_active_status_failure_write_still_works(self):
        """对照：同一条件更新对 PROCESSING 行正常生效（防止 D6 假阳性——
        谓词写错成恒 0 行时 D6 也会通过）。"""
        rid = _new_ai_tool(AI_TOOL_STATUS_PROCESSING)
        affected = AIToolsModel.transition_status(
            rid, list(AI_TOOL_ACTIVE_STATUSES), AI_TOOL_STATUS_FAILED,
            message="任务已过期", completed_time=datetime.now())
        self.assertEqual(affected, 1)
        self.assertEqual(_get_status(rid), AI_TOOL_STATUS_FAILED)


class TestBarrierRaces(unittest.TestCase):
    """R 系列：屏障同步并发竞争，实证 InnoDB 行锁串行化「恰好一方成功」。

    每轮两个线程在 threading.Barrier 处对齐后同时发起 UPDATE；execute_update
    借独立池连接执行（与线上「取消接口线程 vs 调度器线程」同构）。
    """

    ROUNDS = 100

    def _race(self, ops):
        """ops: [(fn) -> affected, ...]；返回各线程 affected 与最终状态。"""
        rid = _new_ai_tool(AI_TOOL_STATUS_PENDING)
        n = len(ops)
        barrier = threading.Barrier(n)
        results = [None] * n
        errors = []

        def runner(i, fn):
            try:
                barrier.wait(timeout=10)
                results[i] = fn(rid)
            except Exception as e:  # noqa: BLE001
                errors.append((i, repr(e)))

        threads = [threading.Thread(target=runner, args=(i, fn)) for i, fn in enumerate(ops)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertFalse(errors, f"竞态线程异常: {errors}")
        self.assertTrue(all(t.is_alive() is False for t in threads), "线程未退出（疑似死锁）")
        return rid, results, _get_status(rid)

    def test_r1_cancel_vs_main_submit_gate(self):
        """I1/I2 核心：取消 vs 0→1 主提交，每轮恰好一方成功。"""
        cancel_won = gate_won = 0
        for _ in range(self.ROUNDS):
            rid, (c, g), final = self._race([
                _cancel,
                lambda r: _gate(r, AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING),
            ])
            self.assertTrue((c == 1) ^ (g == 1),
                            f"互斥被破坏: cancel={c} gate={g} final={final}")
            self.assertIn(final, (AI_TOOL_STATUS_CANCELLED, AI_TOOL_STATUS_PROCESSING))
            if c == 1:
                cancel_won += 1
                self.assertEqual(final, AI_TOOL_STATUS_CANCELLED)
            else:
                gate_won += 1
                self.assertEqual(final, AI_TOOL_STATUS_PROCESSING)
        # 两侧都应至少赢过（证明竞争真实发生而非调度总是串行同序）
        self.assertGreater(cancel_won, 0, "100 轮取消侧全败，竞争可能未真实发生")
        self.assertGreater(gate_won, 0, "100 轮闸门侧全败，竞争可能未真实发生")

    def test_r2_cancel_vs_sync_pool_enqueue(self):
        """0→3 与取消的目标状态重叠（3 仍可取消），合法结局：
        仅取消赢（未入池）/ 仅闸门赢（入池后取消 409）/ 双赢（入池后被取消）。
        S0 不变量：凡最终 CANCELLED，worker 闸门 3→1 必 0 行（绝不调上游）。"""
        both_won = 0
        for _ in range(self.ROUNDS):
            rid, (c, g), final = self._race([
                _cancel,
                lambda r: _gate(r, AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_SYNC_QUEUED),
            ])
            self.assertFalse(c == 0 and g == 0, "双方全败：竞争逻辑异常")
            if c == 1:
                self.assertEqual(final, AI_TOOL_STATUS_CANCELLED)
                # 取消终态下 worker 闸门必失败 → 上游绝不被调用（I1）
                self.assertEqual(
                    _gate(rid, AI_TOOL_STATUS_SYNC_QUEUED, AI_TOOL_STATUS_PROCESSING), 0)
                both_won += g == 1
            else:
                self.assertEqual(final, AI_TOOL_STATUS_SYNC_QUEUED)
                self.assertEqual(g, 1)
        self.assertGreater(both_won, 0, "未观测到「入池后被取消」时序，覆盖不足")

    def test_r3_cancel_vs_param_prepare(self):
        """同 R2 语义：凡最终 CANCELLED，完成推进 4→0 必 0 行（不复活重提交）。"""
        both_won = 0
        for _ in range(self.ROUNDS):
            rid, (c, g), final = self._race([
                _cancel,
                lambda r: _gate(r, AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_WAITING_PARAM_PREPARE),
            ])
            self.assertFalse(c == 0 and g == 0)
            if c == 1:
                self.assertEqual(final, AI_TOOL_STATUS_CANCELLED)
                self.assertEqual(
                    _gate(rid, AI_TOOL_STATUS_WAITING_PARAM_PREPARE, AI_TOOL_STATUS_PENDING), 0)
                both_won += g == 1
            else:
                self.assertEqual(final, AI_TOOL_STATUS_WAITING_PARAM_PREPARE)
                self.assertEqual(g, 1)
        self.assertGreater(both_won, 0, "未观测到「进入预处理后被取消」时序，覆盖不足")

    def test_r4_concurrent_double_cancel_exactly_one_refund_path(self):
        """I3：并发双取消，恰好一个 affected=1（只有胜者会走退费分支）。"""
        for _ in range(self.ROUNDS):
            rid, (c1, c2), final = self._race([_cancel, _cancel])
            self.assertEqual(c1 + c2, 1, f"双取消互斥破坏: {c1}+{c2}")
            self.assertEqual(final, AI_TOOL_STATUS_CANCELLED)


class TestRefundIdempotency(unittest.TestCase):
    """I3：退费幂等键 DB 层验证（不触发真实 perseids 退款 HTTP）。"""

    def test_refund_key_format_and_guard(self):
        import uuid
        from utils.computing_power import build_refund_transaction_id, is_already_refunded
        from model.computing_power_log import ComputingPowerLogModel

        txn = f"s0-charge-{uuid.uuid4().hex[:10]}"
        rid = _new_ai_tool(AI_TOOL_STATUS_PENDING, transaction_id=txn, user_id=424242)
        tool = AIToolsModel.get_by_id(rid)
        self.assertEqual(build_refund_transaction_id(tool), f"refund-{txn}")

        # 未退费 → 守卫放行
        self.assertFalse(is_already_refunded(tool))
        # 写入退费流水（模拟 perseids 落库）→ 守卫拦截二次退费
        execute_update(
            "INSERT INTO computing_power_log (transaction_id, user_id, computing_power, "
            "behavior, message, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (f"refund-{txn}", 424242, -10, 2, "用户取消排队任务", datetime.now()))
        self.assertTrue(is_already_refunded(tool))
        self.assertTrue(ComputingPowerLogModel.check_transaction_exists(f"refund-{txn}"))

    def test_cancelled_then_refunded_task_never_resurrects(self):
        """I1+I3 组合：取消退费后的任务，任何闸门/失败写入都无法复活。"""
        rid = _new_ai_tool(AI_TOOL_STATUS_PENDING, transaction_id="s0-charge-txn-002")
        self.assertEqual(_cancel(rid), 1)
        self.assertEqual(
            _gate(rid, AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING), 0)
        self.assertEqual(
            AIToolsModel.transition_status(
                rid, list(AI_TOOL_ACTIVE_STATUSES), AI_TOOL_STATUS_FAILED,
                message="任务已过期", completed_time=datetime.now()), 0)
        self.assertEqual(_get_status(rid), AI_TOOL_STATUS_CANCELLED)


class TestTasksTableConvergence(unittest.TestCase):
    """I4：ai_tools 权威迁移后 tasks 表同步（调度器查询依据），取消后不再拾取。"""

    def test_cancelled_task_not_picked_by_scheduler_query(self):
        from model.tasks import TasksModel
        rid = _new_ai_tool(AI_TOOL_STATUS_PENDING)
        execute_update(
            "INSERT INTO tasks (task_type, task_id, status, next_trigger) "
            "VALUES (%s, %s, %s, %s)",
            (2, rid, 0, datetime.now() - timedelta(seconds=1)))
        self.assertEqual(_cancel(rid), 1)
        # 模拟取消接口对 tasks 的同步写
        TasksModel.update_by_task_id(rid, status=-2)
        pending = TasksModel.list_by_type_and_status("generate_video", status_list=[0, 1])
        self.assertNotIn(rid, [t.task_id for t in pending],
                         "CANCELLED 任务仍会被调度器拾取")


if __name__ == "__main__":
    unittest.main()
