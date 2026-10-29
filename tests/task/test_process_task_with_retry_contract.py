"""调度循环 process_task_with_retry 的返回值五态契约回归测试。

背景（fix 36b927be「修复失败任务被统计为成功」）：处理函数返回值由
True/False 二分演进为 SUCCESS/FAILED/IN_FLIGHT/True/False 五态。此前
FAILED 被计入 success_count，且对已被失败处理器落成终态的任务虚增
try_count、打 RETRY_SCHEDULED 假重试日志。既有测试只覆盖各处理函数
「返回什么」，本文件守护调度循环「如何消费」这些值：

- SUCCESS / True(遗留) → 计入 success_count，不安排重试
- FAILED  → 终态失败，不计成功、不退避、不增 try_count
- IN_FLIGHT → 在途，不动 try_count
- False/None → transient，try_count+1 + 退避 + RETRY_SCHEDULED 日志
  （且轮询中 vs 真失败文案区分）
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from task import visual_task


def _setup(monkeypatch, result_value, *, ai_status=None, project_id="p1", try_count=0):
    """搭好调度循环最小环境，返回 (updates, log_calls)。"""
    task = SimpleNamespace(
        task_id="t-contract-1",
        id=101,
        status=visual_task.TASK_STATUS_PROCESSING,
        try_count=try_count,
    )
    ai_tool = SimpleNamespace(
        id=101,
        type=-1,  # 非 RunningHub 任务，跳过槽位控制
        user_id=9,
        project_id=project_id,
        implementation=None,
        status=ai_status,
    )

    def fake_list(_task_type, status_list=None):
        # 首次调用取待处理任务；函数末尾卡死恢复按 WAITING_BEFORE_FINISH 再查一次
        if status_list == [visual_task.TASK_STATUS_WAITING_BEFORE_FINISH]:
            return []
        return [task]

    monkeypatch.setattr(visual_task.TasksModel, "list_by_type_and_status", fake_list)
    monkeypatch.setattr(visual_task, "_check_task_expiration", lambda _t: False)
    monkeypatch.setattr(visual_task, "_check_max_retry_exceeded", lambda _t: False)
    monkeypatch.setattr(visual_task.AIToolsModel, "get_by_id", lambda _tid: ai_tool)

    updates = []
    monkeypatch.setattr(
        visual_task.TasksModel,
        "update_by_task_id",
        lambda *a, **kw: updates.append((a, kw)),
    )
    logs = []
    monkeypatch.setattr(
        visual_task.AIToolsLogModel,
        "log",
        lambda *a, **kw: logs.append((a, kw)),
    )

    def process_func(_task):
        return result_value

    return process_func, updates, logs


def _retry_logs(logs):
    return [
        kw.get("message", "")
        for a, kw in logs
        if len(a) > 1 and a[1] == visual_task.AIToolsLogEvent.RETRY_SCHEDULED
    ]


def test_success_result_counts_as_succeeded(monkeypatch):
    func, updates, logs = _setup(monkeypatch, visual_task.PROCESS_RESULT_SUCCESS)
    has_task, any_succeeded = visual_task.process_task_with_retry("tt", func)
    assert (has_task, any_succeeded) == (True, True)
    assert not _retry_logs(logs)
    assert all("try_count" not in kw for _a, kw in updates)


def test_legacy_true_still_counts_as_success(monkeypatch):
    func, updates, logs = _setup(monkeypatch, True)
    has_task, any_succeeded = visual_task.process_task_with_retry("tt", func)
    assert (has_task, any_succeeded) == (True, True)
    assert not _retry_logs(logs)


def test_failed_result_not_counted_as_success(monkeypatch):
    """FAILED 不得计入 success_count（回归 36b927be 修复的统计 bug）。"""
    func, updates, logs = _setup(monkeypatch, visual_task.PROCESS_RESULT_FAILED)
    has_task, any_succeeded = visual_task.process_task_with_retry("tt", func)
    assert (has_task, any_succeeded) == (True, False)
    # 已是终态失败：不得虚增 try_count / 打假 RETRY_SCHEDULED 日志
    assert not _retry_logs(logs)
    assert all("try_count" not in kw for _a, kw in updates)


def test_in_flight_leaves_retry_state_untouched(monkeypatch):
    func, updates, logs = _setup(monkeypatch, visual_task.PROCESS_RESULT_IN_FLIGHT)
    has_task, any_succeeded = visual_task.process_task_with_retry("tt", func)
    assert (has_task, any_succeeded) == (True, False)
    assert not updates  # 状态由处理函数自行维护
    assert not _retry_logs(logs)


def test_false_transient_schedules_backoff_retry(monkeypatch):
    func, updates, logs = _setup(
        monkeypatch, False,
        ai_status=visual_task.AI_TOOL_STATUS_FAILED, project_id=None,
    )
    has_task, any_succeeded = visual_task.process_task_with_retry("tt", func)
    assert (has_task, any_succeeded) == (True, False)

    retry_updates = [kw for _a, kw in updates if "try_count" in kw]
    assert len(retry_updates) == 1
    assert retry_updates[0]["try_count"] == 1
    assert "next_trigger" in retry_updates[0]

    messages = _retry_logs(logs)
    assert len(messages) == 1
    assert "处理失败" in messages[0]


def test_none_while_polling_uses_polling_copy(monkeypatch):
    """轮询中的 False/None（RUNNING）文案须为「任务处理中」，不误报处理失败。"""
    func, updates, logs = _setup(
        monkeypatch, None,
        ai_status=visual_task.AI_TOOL_STATUS_PROCESSING, project_id="p1",
    )
    has_task, any_succeeded = visual_task.process_task_with_retry("tt", func)
    assert (has_task, any_succeeded) == (True, False)

    messages = _retry_logs(logs)
    assert len(messages) == 1
    assert "任务处理中" in messages[0]
    assert "处理失败" not in messages[0]

    retry_updates = [kw for _a, kw in updates if "try_count" in kw]
    assert retry_updates[0]["try_count"] == 1


def test_try_count_increments_from_existing(monkeypatch):
    func, updates, _logs = _setup(
        monkeypatch, False, try_count=3,
        ai_status=visual_task.AI_TOOL_STATUS_FAILED, project_id=None,
    )
    visual_task.process_task_with_retry("tt", func)
    retry_updates = [kw for _a, kw in updates if "try_count" in kw]
    assert retry_updates[0]["try_count"] == 4


def test_process_func_exception_backoff(monkeypatch):
    """处理函数抛异常 → 捕获后退避（try_count+1），不让整个循环崩掉。"""
    task = SimpleNamespace(task_id="t-err", id=102,
                           status=visual_task.TASK_STATUS_PROCESSING, try_count=0)
    ai_tool = SimpleNamespace(id=102, type=-1, user_id=9,
                              project_id=None, implementation=None, status=None)

    def fake_list(_task_type, status_list=None):
        if status_list == [visual_task.TASK_STATUS_WAITING_BEFORE_FINISH]:
            return []
        return [task]

    monkeypatch.setattr(visual_task.TasksModel, "list_by_type_and_status", fake_list)
    monkeypatch.setattr(visual_task, "_check_task_expiration", lambda _t: False)
    monkeypatch.setattr(visual_task, "_check_max_retry_exceeded", lambda _t: False)
    monkeypatch.setattr(visual_task.AIToolsModel, "get_by_id", lambda _tid: ai_tool)
    updates = []
    monkeypatch.setattr(
        visual_task.TasksModel, "update_by_task_id",
        lambda *a, **kw: updates.append((a, kw)))
    monkeypatch.setattr(
        visual_task.AIToolsLogModel, "log", lambda *a, **kw: None)

    def boom(_task):
        raise RuntimeError("driver exploded")

    # 异常发生在 processed_count += 1 之前 → has_task=False，但退避更新仍落库
    has_task, any_succeeded = visual_task.process_task_with_retry("tt", boom)
    assert (has_task, any_succeeded) == (False, False)
    retry_updates = [kw for _a, kw in updates if "try_count" in kw]
    assert len(retry_updates) == 1
    assert retry_updates[0]["try_count"] == 1


def test_no_pending_tasks_returns_false_false(monkeypatch):
    monkeypatch.setattr(
        visual_task.TasksModel, "list_by_type_and_status",
        lambda _task_type, status_list=None: [])
    has_task, any_succeeded = visual_task.process_task_with_retry(
        "tt", lambda _t: visual_task.PROCESS_RESULT_SUCCESS)
    assert (has_task, any_succeeded) == (False, False)
