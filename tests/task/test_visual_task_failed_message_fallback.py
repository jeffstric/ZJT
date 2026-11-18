"""check_status FAILED 结果的 error/message 键消费兼容。

部分驱动（如晨羽 H3 chenyu_v1）FAILED 分支只回 ``message`` 键而非主契约
``error`` 键，消费端此前只读 ``error``——真实失败原因（内容审核拒绝/GPU
异常等）丢失成兜底文案"任务失败"，用户与客服无法排障。此回归测试锁定
消费端 ``error or message`` 兜底顺序。
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from task import visual_task


def _setup_common(monkeypatch, check_result):
    fake_executor = MagicMock()
    fake_executor.is_task_running.return_value = False
    monkeypatch.setattr("task.sync_task_executor.get_sync_task_executor", lambda: fake_executor)
    monkeypatch.setattr("task.mock_interceptor.is_mock_enabled", lambda: False)

    driver = SimpleNamespace(
        driver_name="message-only-driver",
        check_status=lambda _project_id: check_result,
    )
    monkeypatch.setattr(
        "task.visual_drivers.VideoDriverFactory.create_driver_by_type_result",
        lambda *_args, **_kwargs: (driver, None),
    )
    monkeypatch.setattr(visual_task.AIToolsLogModel, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        visual_task.TasksModel,
        "get_by_task_id",
        lambda _task_id: SimpleNamespace(try_count=0),
    )
    monkeypatch.setattr(visual_task.TasksModel, "update_by_task_id", lambda *a, **k: None)

    captured = {}

    def fake_handle_failure(task_id, ai_tool_type, reason, user_id, **kwargs):
        captured["reason"] = reason
        return "failure-handled"

    monkeypatch.setattr(visual_task, "_handle_task_failure", fake_handle_failure)

    ai_tool = SimpleNamespace(id=201, project_id="project-201", type=-1, user_id=1, implementation=None)
    return captured, ai_tool


def test_failed_with_message_only_falls_back_to_message(monkeypatch):
    """只回 message 键的驱动：真实原因透传给失败处理，不丢成“任务失败”"""
    captured, ai_tool = _setup_common(monkeypatch, {
        "status": "FAILED",
        "message": "上游内容审核拒绝",
    })
    asyncio.run(visual_task._check_task_status(ai_tool))
    assert captured["reason"] == "上游内容审核拒绝"


def test_failed_with_error_key_still_wins(monkeypatch):
    """回 error 键的驱动（主契约）不受兜底影响，message 不覆盖 error"""
    captured, ai_tool = _setup_common(monkeypatch, {
        "status": "FAILED",
        "error": "余额不足",
        "message": "不应覆盖 error",
    })
    asyncio.run(visual_task._check_task_status(ai_tool))
    assert captured["reason"] == "余额不足"


def test_failed_without_any_reason_uses_default(monkeypatch):
    """两个键都没有：保持原兜底文案，行为不回退"""
    captured, ai_tool = _setup_common(monkeypatch, {"status": "FAILED"})
    asyncio.run(visual_task._check_task_status(ai_tool))
    assert captured["reason"] == "任务失败"
