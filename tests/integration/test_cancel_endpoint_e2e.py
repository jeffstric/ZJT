"""
排队任务取消 S0 验证——HTTP 端点层 E2E（L3 自动化子集）

前置（见 docs/video/queued_task_cancel_rebase_test_plan.md）：
  1. 隔离服务实例已启动：comfyui_env=s0test python server.py
     （config_s0test.yml → 端口 13117、数据库 zjt_cancel_test@13314）
  2. 测试 token：user_tokens 表 's0-test-token-424242' → user_id 424242
  服务未启动时整体 skip。

覆盖：E1 取消全链路 / E2 生成中 409 / E5 双取消 / 属主 403 /
E6 步骤连带取消 / E4 HTTP×DB 闸门竞态 / E11 退款失败路径 / get-status 前端契约。

⚠️ 退费安全：perseids 指向生产。所有常规用例通过预插 refund 流水触发幂等跳过
（零外部调用）；仅 test_e11 故意走一次真实退款失败（user 424242 在生产不存在，
调用必然失败、不产生资金变动）。
"""
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from datetime import datetime

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

BASE = os.environ.get("S0_BASE_URL", "http://127.0.0.1:13117")
TOKEN = "s0-test-token-424242"
USER = 424242


def _http(method, path, token=TOKEN, timeout=30):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _server_up() -> bool:
    """只测 TCP/HTTP 连通性（/health 返回 HTML，不能按 JSON 解析）。"""
    try:
        req = urllib.request.Request(BASE + "/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return 200 <= resp.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500  # 404 等也证明服务在线
    except Exception:
        return False


if not _server_up():
    raise unittest.SkipTest(f"隔离服务未启动({BASE})，HTTP E2E 整体跳过")

# 服务在线才导入 DB 层（与隔离实例同一测试库）
import model.database as _dbmod  # noqa: E402
_dbmod.DB_CONFIG.update(host="127.0.0.1", port=int(os.environ.get("CANCEL_TEST_PORT", "13314")),
                        user="root", password="3bTgThWP2xeX",
                        database=os.environ.get("CANCEL_TEST_DB", "zjt_cancel_test"))
_dbmod._pool = None

from config.constant import (  # noqa: E402
    AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_WAITING_PARAM_PREPARE, AI_TOOL_STATUS_CANCELLED,
    AI_TOOL_CANCELLABLE_STATUSES,
)
from model.ai_tools import AIToolsModel  # noqa: E402
from model.database import execute_query, execute_update  # noqa: E402


def _new_task(status=AI_TOOL_STATUS_PENDING, user_id=USER, with_tasks_row=True,
              txn=None, project_id=None, **fields):
    row = execute_query("SELECT COALESCE(MAX(id),1) AS m FROM ai_tools", fetch_one=True)
    rid = int(row["m"]) + 1
    cols = {"id": rid, "type": 5, "status": status, "prompt": "e2e", "user_id": user_id,
            "create_time": datetime.now(), "update_time": datetime.now()}
    if txn:
        cols["transaction_id"] = txn
    if project_id:
        cols["project_id"] = project_id
    cols.update(fields)
    execute_update(
        f"INSERT INTO ai_tools ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        tuple(cols.values()))
    if with_tasks_row:
        execute_update(
            "INSERT INTO tasks (task_type, task_id, status, next_trigger) VALUES (%s,%s,0,NOW())",
            ("generate_video", rid))
    return rid


def _ai(rid):
    return execute_query("SELECT * FROM ai_tools WHERE id=%s", (rid,), fetch_one=True)


def _tasks_status(rid):
    row = execute_query("SELECT status FROM tasks WHERE task_id=%s ORDER BY id DESC LIMIT 1",
                        (rid,), fetch_one=True)
    return row["status"] if row else None


def _pre_refund(txn):
    """预插退费流水 → 取消接口退费幂等跳过（零外部 HTTP）。"""
    execute_update(
        "INSERT INTO computing_power_log (transaction_id, user_id, computing_power, "
        "behavior, message, created_at) VALUES (%s,%s,-10,2,'预置退费',NOW())",
        (f"refund-{txn}", USER))


class TestCancelEndpointE2E(unittest.TestCase):

    def test_e1_queued_cancel_full_flow(self):
        """E1 主路径：PENDING → 取消成功，双表 -2、completed_time 落库、
        幂等跳过退费（无「退款处理中」提示）、取消日志就位。"""
        txn = f"s0-{uuid.uuid4().hex[:10]}"
        rid = _new_task(txn=txn)
        _pre_refund(txn)

        status, body = _http("POST", f"/api/ai-tool/{rid}/cancel")
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["status"], "CANCELLED")
        self.assertNotIn("退款处理中", body["message"], "预置退费流水应被幂等跳过")

        ai = _ai(rid)
        self.assertEqual(ai["status"], AI_TOOL_STATUS_CANCELLED)
        self.assertIsNotNone(ai["completed_time"])
        self.assertEqual(_tasks_status(rid), -2)
        log = execute_query(
            "SELECT event_type FROM ai_tools_log WHERE ai_tool_id=%s "
            "AND status_to=%s ORDER BY id DESC LIMIT 1",
            (rid, AI_TOOL_STATUS_CANCELLED), fetch_one=True)
        self.assertTrue(log, "取消日志未落库")

    def test_e2_processing_rejects_409(self):
        """E2：已提交上游（PROCESSING + project_id）→ 409 且状态不变（I2）。"""
        rid = _new_task(status=AI_TOOL_STATUS_PROCESSING, project_id="rh-abc")
        status, body = _http("POST", f"/api/ai-tool/{rid}/cancel")
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], -1)
        self.assertEqual(_ai(rid)["status"], AI_TOOL_STATUS_PROCESSING)
        self.assertEqual(_tasks_status(rid), 0)

    def test_e5_double_cancel_second_409(self):
        rid = _new_task()
        s1, _ = _http("POST", f"/api/ai-tool/{rid}/cancel")
        s2, body2 = _http("POST", f"/api/ai-tool/{rid}/cancel")
        self.assertEqual(s1, 200)
        self.assertEqual(s2, 409)
        self.assertEqual(_ai(rid)["status"], AI_TOOL_STATUS_CANCELLED)

    def test_ownership_mismatch_403(self):
        rid = _new_task(user_id=999999)
        status, body = _http("POST", f"/api/ai-tool/{rid}/cancel")
        self.assertEqual(status, 403)
        self.assertEqual(_ai(rid)["status"], AI_TOOL_STATUS_PENDING)

    def test_no_auth_401(self):
        rid = _new_task()
        status, _ = _http("POST", f"/api/ai-tool/{rid}/cancel", token=None)
        self.assertEqual(status, 401)
        self.assertEqual(_ai(rid)["status"], AI_TOOL_STATUS_PENDING)

    def test_e6_pipeline_steps_cancelled_together(self):
        """E6：预处理排队中取消 → 未执行步骤连带 CANCELLED，执行中步骤不动。"""
        rid = _new_task(status=AI_TOOL_STATUS_WAITING_PARAM_PREPARE)
        steps = []
        for i, st in enumerate((0, 0, 1)):  # 两条 PENDING、一条 PROCESSING
            execute_update(
                "INSERT INTO ai_tool_pipeline_steps (ai_tool_id, stage, step_type, status, "
                "created_at, updated_at) VALUES (%s,'param_prepare','face_mask',%s,NOW(),NOW())",
                (rid, st))
            row = execute_query("SELECT id FROM ai_tool_pipeline_steps ORDER BY id DESC",
                                fetch_one=True)
            steps.append(row["id"])

        status, body = _http("POST", f"/api/ai-tool/{rid}/cancel")
        self.assertEqual(status, 200)
        rows = execute_query(
            "SELECT id, status FROM ai_tool_pipeline_steps WHERE ai_tool_id=%s", (rid,),
            fetch_all=True)
        by_id = {r["id"]: r["status"] for r in rows}
        self.assertEqual(by_id[steps[0]], -3)
        self.assertEqual(by_id[steps[1]], -3)
        self.assertEqual(by_id[steps[2]], 1, "执行中步骤不应被连改为 CANCELLED")

    def test_e4b_http_cancel_first_gate_never_wins(self):
        """I1 经真实端点：HTTP 取消成功后，调度器闸门 0→1 必 0 行
        （上游绝不被调用），且再次取消返回 409。"""
        rid = _new_task()
        status, body = _http("POST", f"/api/ai-tool/{rid}/cancel")
        self.assertEqual(status, 200)
        affected = AIToolsModel.transition_status(
            rid, [AI_TOOL_STATUS_PENDING], AI_TOOL_STATUS_PROCESSING)
        self.assertEqual(affected, 0, "取消终态后闸门仍抢占成功 = S0 互斥破坏")
        self.assertIsNone(_ai(rid)["project_id"], "已取消任务不应有上游 project_id")

    def test_e4_http_cancel_vs_db_gate_race(self):
        """E4 竞争窗口：HTTP 取消线程 × 调度器闸门（DB 直连）并发，
        每轮恰好一方成功；取消赢 → 上游闸门必 0 行（I1）。"""
        rounds, cancel_won, gate_won = 20, 0, 0
        for _ in range(rounds):
            rid = _new_task()
            barrier = threading.Barrier(2)
            out = {}

            def http_cancel():
                barrier.wait(timeout=10)
                out["cancel"] = _http("POST", f"/api/ai-tool/{rid}/cancel")

            def db_gate():
                barrier.wait(timeout=10)
                out["gate"] = AIToolsModel.transition_status(
                    rid, [AI_TOOL_STATUS_PENDING], AI_TOOL_STATUS_PROCESSING)

            threads = [threading.Thread(target=http_cancel), threading.Thread(target=db_gate)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            cancel_ok = out["cancel"][0] == 200
            gate_ok = out["gate"] == 1
            self.assertTrue(cancel_ok ^ gate_ok,
                            f"互斥破坏: cancel={out['cancel'][0]} gate={out['gate']}")
            final = _ai(rid)["status"]
            if cancel_ok:
                cancel_won += 1
                self.assertEqual(final, AI_TOOL_STATUS_CANCELLED)
            else:
                gate_won += 1
                self.assertEqual(final, AI_TOOL_STATUS_PROCESSING)
        self.assertGreater(cancel_won + gate_won, 0)
        print(f"\nE4 竞态 20 轮: 取消赢 {cancel_won}, 闸门赢 {gate_won}")

    @unittest.expectedFailure
    def test_e11_refund_failure_path(self):
        """E11（缺陷记录）：退款失败时响应应提示「退款处理中」。

        实测证明该提示为死代码：_refund_computing_power 所有失败路径均静默
        return（task/visual_task.py:250-274，含外层 except 吞异常），永不向上
        抛 → 取消接口 refund_done 恒 True → 用户永远看到「任务已取消」，
        退款失败只能靠 L4 对账名单发现。缺陷修复后本用例应转绿（去 xfail）。"""
        txn = f"s0-norefund-{uuid.uuid4().hex[:8]}"
        rid = _new_task(txn=txn)
        execute_update(
            "INSERT INTO computing_power_log (transaction_id, user_id, computing_power, "
            "behavior, message, created_at) VALUES (%s,%s,-10,1,'扣费',NOW())",
            (txn, USER))
        status, body = _http("POST", f"/api/ai-tool/{rid}/cancel")
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 0)
        self.assertIn("退款处理中", body["message"],
                      "退款失败应向用户明示（当前为死代码，见用例 docstring）")
        self.assertEqual(_ai(rid)["status"], AI_TOOL_STATUS_CANCELLED,
                         "退款失败不得回滚取消终态")

    def test_get_status_contract_queued_and_cancelled(self):
        """前端契约：get-status 对排队状态返回 QUEUED、取消后返回 CANCELLED。"""
        rid = _new_task()
        s, body = _http("GET", f"/api/get-status/{rid}")
        self.assertEqual(s, 200)
        task = next(t for t in body["tasks"] if int(t["project_id"]) == rid)
        self.assertEqual(task["status"], "QUEUED")

        _http("POST", f"/api/ai-tool/{rid}/cancel")
        s, body = _http("GET", f"/api/get-status/{rid}")
        task = next(t for t in body["tasks"] if int(t["project_id"]) == rid)
        self.assertEqual(task["status"], "CANCELLED")
        self.assertTrue(task.get("reason"))


if __name__ == "__main__":
    unittest.main()
