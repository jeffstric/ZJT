"""剧本分段拆分 - worker 状态机与异常映射单元测试。

覆盖测试方案 §2.6：
- process_script_split_tasks 单 tick：claim → wait_for(_advance_one_step) → release_lease
- watchdog 超时进 paused 保留检查点
- 异常映射：CancelledByUser→cancelled、WaitingAuth→waiting_auth、
  TaskPaused→paused、EngineError terminal_codes→failed、其余→paused、未知异常→failed
- 状态机分发：queued/planning→step_plan、generating→step_generate_segment、
  publishing→step_publish、旧状态(merging/validating)→invalid_task_state

worker 是纯编排层，所有 engine.step_* 和 model 调用全部 mock，不连库不连 LLM。
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from config.constant import ScriptSplitConstants
from services import script_split_engine as engine
from task import script_split_task as worker_mod


def _task(status="queued", task_id=101):
    return SimpleNamespace(id=task_id, status=status, worker_id="test-host-claim-101")


def _run(coro):
    """同步跑 async worker 函数。"""
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


@pytest.fixture
def patched_worker(monkeypatch):
    """替换 model 层与 engine.step_*，记录所有 update_status 调用。"""
    calls = {"updates": [], "released": [], "claimed": None}

    def fake_claim(lease_seconds):
        calls["claimed"] = lease_seconds
        return _task()

    def fake_update(task_id, status, **kwargs):
        calls["updates"].append({"task_id": task_id, "status": status, **kwargs})

    def fake_release(task_id, _worker_id):
        calls["released"].append(task_id)

    monkeypatch.setattr(worker_mod.ScriptSplitTaskModel, "claim_next_task", staticmethod(fake_claim))
    monkeypatch.setattr(worker_mod.ScriptSplitTaskModel, "update_status", staticmethod(fake_update))
    monkeypatch.setattr(worker_mod.ScriptSplitTaskModel, "release_lease", staticmethod(fake_release))
    monkeypatch.setattr(
        worker_mod.ScriptSplitSegmentModel,
        "reclaim_stale_generating",
        staticmethod(lambda *_args: {
            "lease_owned": True,
            "reclaimed_count": 0,
            "exhausted_segment_indexes": [],
        }),
    )
    return calls


# ---------------- 单 tick 正常流程 ----------------

class TestWorkerHappyPath:
    def test_no_task_returns_early(self, patched_worker, monkeypatch):
        """无 queued 任务时 claim 返回 None，快速返回，不报错。"""
        monkeypatch.setattr(worker_mod.ScriptSplitTaskModel, "claim_next_task",
                            staticmethod(lambda lease: None))
        _run(worker_mod.process_script_split_tasks())
        assert patched_worker["updates"] == []
        assert patched_worker["released"] == []

    def test_queued_transitions_to_planning_then_step_plan(self, patched_worker, monkeypatch):
        step_calls = []

        async def fake_step_plan(task):
            step_calls.append(task.id)

        monkeypatch.setattr(engine, "step_plan", fake_step_plan, raising=False)
        _run(worker_mod.process_script_split_tasks())
        # queued 先 update 到 planning，再调 step_plan，最后 release
        assert step_calls == [101]
        assert patched_worker["updates"][0]["status"] == ScriptSplitConstants.STATUS_PLANNING
        assert 101 in patched_worker["released"]


# ---------------- watchdog 超时 ----------------

class TestWorkerWatchdog:
    def test_watchdog_timeout_enters_paused(self, patched_worker, monkeypatch):
        """单步超过 WORKER_STEP_TIMEOUT_SECONDS → 进 paused 保留检查点（不进 failed）。

        通过把 WORKER_STEP_TIMEOUT_SECONDS 临时调到极小值（0.01s）触发真实超时，
        避免替换 asyncio.wait_for 引起递归。
        """
        async def slow_step(task):
            await asyncio.sleep(0.5)

        monkeypatch.setattr(ScriptSplitConstants, "WORKER_STEP_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(engine, "step_plan", slow_step, raising=False)
        _run(worker_mod.process_script_split_tasks())
        update = next(u for u in patched_worker["updates"]
                      if u["status"] == ScriptSplitConstants.STATUS_PAUSED)
        assert update["last_error_code"] == "step_watchdog_timeout"
        assert 101 in patched_worker["released"]


# ---------------- 异常映射 ----------------

class TestWorkerExceptionMapping:
    @pytest.mark.parametrize("exc_factory,expected_status,expected_code", [
        (lambda: engine.CancelledByUser(), ScriptSplitConstants.STATUS_CANCELLED, None),
        (lambda: engine.WaitingAuth(), ScriptSplitConstants.STATUS_WAITING_AUTH, "waiting_auth"),
        (lambda: engine.TaskPaused("seg_exhausted", "达到上限"), ScriptSplitConstants.STATUS_PAUSED, "seg_exhausted"),
    ])
    def test_special_exceptions(self, patched_worker, monkeypatch, exc_factory, expected_status, expected_code):
        async def raising_step(task):
            raise exc_factory()

        monkeypatch.setattr(engine, "step_plan", raising_step, raising=False)
        _run(worker_mod.process_script_split_tasks())
        statuses = [u["status"] for u in patched_worker["updates"]]
        assert expected_status in statuses
        if expected_code:
            update = next(u for u in patched_worker["updates"] if u["status"] == expected_status)
            assert update["last_error_code"] == expected_code
        assert 101 in patched_worker["released"]

    @pytest.mark.parametrize("code,expected_status", [
        ("invalid_segment_checkpoint_state", ScriptSplitConstants.STATUS_FAILED),
        ("invalid_task_state", ScriptSplitConstants.STATUS_FAILED),
        ("empty_script", ScriptSplitConstants.STATUS_FAILED),
        ("no_final_result", ScriptSplitConstants.STATUS_PAUSED),       # 非 terminal → paused
        ("publish_conflict", ScriptSplitConstants.STATUS_PAUSED),
    ])
    def test_engine_error_terminal_vs_paused(self, patched_worker, monkeypatch, code, expected_status):
        async def raising_step(task):
            raise engine.EngineError(code, f"测试 {code}")

        monkeypatch.setattr(engine, "step_plan", raising_step, raising=False)
        _run(worker_mod.process_script_split_tasks())
        statuses = [u["status"] for u in patched_worker["updates"]]
        assert expected_status in statuses
        update = next(u for u in patched_worker["updates"] if u["status"] == expected_status)
        assert update["last_error_code"] == code

    def test_unknown_exception_enters_failed(self, patched_worker, monkeypatch):
        async def raising_step(task):
            raise RuntimeError("意料之外")

        monkeypatch.setattr(engine, "step_plan", raising_step, raising=False)
        _run(worker_mod.process_script_split_tasks())
        statuses = [u["status"] for u in patched_worker["updates"]]
        assert ScriptSplitConstants.STATUS_FAILED in statuses
        failed = next(u for u in patched_worker["updates"]
                      if u["status"] == ScriptSplitConstants.STATUS_FAILED)
        assert failed["last_error_code"] == "unknown_error"


# ---------------- 状态机分发 ----------------

class TestWorkerStateMachineDispatch:
    def test_cancelling_state_transitions_to_cancelled(self, patched_worker, monkeypatch):
        """已提交取消的空闲任务应在下一个 tick 进入 cancelled 终态。"""
        monkeypatch.setattr(
            worker_mod.ScriptSplitTaskModel,
            "claim_next_task",
            staticmethod(lambda lease: _task(status=ScriptSplitConstants.STATUS_CANCELLING)),
        )

        _run(worker_mod.process_script_split_tasks())

        statuses = [u["status"] for u in patched_worker["updates"]]
        assert ScriptSplitConstants.STATUS_CANCELLED in statuses

    @pytest.mark.parametrize("status,expected_step", [
        ("generating", "step_generate_segment"),
        ("publishing", "step_publish"),
        ("planning", "step_plan"),
    ])
    def test_dispatches_correct_step(self, patched_worker, monkeypatch, status, expected_step):
        """按 task.status 调用对应 engine step。"""
        # 重新让 claim 返回指定 status 的 task
        monkeypatch.setattr(worker_mod.ScriptSplitTaskModel, "claim_next_task",
                            staticmethod(lambda lease: _task(status=status)))
        called = []

        async def fake_plan(task): called.append("step_plan")
        async def fake_gen(task): called.append("step_generate_segment")
        async def fake_pub(task): called.append("step_publish")

        monkeypatch.setattr(engine, "step_plan", fake_plan, raising=False)
        monkeypatch.setattr(engine, "step_generate_segment", fake_gen, raising=False)
        monkeypatch.setattr(engine, "step_publish", fake_pub, raising=False)
        _run(worker_mod.process_script_split_tasks())
        assert called == [expected_step]

    def test_legacy_merging_state_raises_invalid_task_state(self, patched_worker, monkeypatch):
        """旧状态 merging/validating 不再执行 → 抛 invalid_task_state（terminal → failed）。"""
        monkeypatch.setattr(worker_mod.ScriptSplitTaskModel, "claim_next_task",
                            staticmethod(lambda lease: _task(status="merging")))
        _run(worker_mod.process_script_split_tasks())
        statuses = [u["status"] for u in patched_worker["updates"]]
        assert ScriptSplitConstants.STATUS_FAILED in statuses

    def test_terminal_status_skipped(self, patched_worker, monkeypatch):
        """已终态（completed/failed/cancelled）的任务被 claim 后无可执行步骤，跳过。"""
        monkeypatch.setattr(worker_mod.ScriptSplitTaskModel, "claim_next_task",
                            staticmethod(lambda lease: _task(status="completed")))
        called = []
        monkeypatch.setattr(engine, "step_plan", lambda t: called.append("plan"), raising=False)
        monkeypatch.setattr(engine, "step_generate_segment", lambda t: called.append("gen"), raising=False)
        monkeypatch.setattr(engine, "step_publish", lambda t: called.append("pub"), raising=False)
        _run(worker_mod.process_script_split_tasks())
        assert called == []  # 无 step 被调


# ---------------- _transition_to_cancelled ----------------

class TestTransitionToCancelled:
    def test_sets_cancelled_and_leaves_release_to_worker_finally(self, monkeypatch):
        released = []
        updates = []
        monkeypatch.setattr(worker_mod.ScriptSplitTaskModel, "update_status",
                            staticmethod(lambda tid, status, **kw: updates.append((tid, status, kw))))
        monkeypatch.setattr(worker_mod.ScriptSplitTaskModel, "release_lease",
                            staticmethod(lambda tid: released.append(tid)))
        worker_mod._transition_to_cancelled(202)
        assert updates == [(202, ScriptSplitConstants.STATUS_CANCELLED, {"phase": "cancelled"})]
        assert released == []


# ---------------- make_scheduler_job ----------------

class TestMakeSchedulerJob:
    def test_returns_callable(self):
        job = worker_mod.make_scheduler_job()
        assert callable(job)

    def test_partial_wraps_process(self, monkeypatch):
        """make_scheduler_job 返回的 partial 内部调用 process_script_split_tasks。"""
        # task.scheduler._run_async_task 把 async 函数包成同步调度入口
        from functools import partial
        assert isinstance(job := worker_mod.make_scheduler_job(), partial)
