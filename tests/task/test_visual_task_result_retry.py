"""上游成功后的结果获取重试不得消耗生成阶段重试次数。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from task import visual_task


def test_result_fetch_retry_preserves_generation_try_count(monkeypatch):
    fake_executor = MagicMock()
    fake_executor.is_task_running.return_value = False
    monkeypatch.setattr("task.sync_task_executor.get_sync_task_executor", lambda: fake_executor)
    monkeypatch.setattr("task.mock_interceptor.is_mock_enabled", lambda: False)

    driver = SimpleNamespace(
        driver_name="result-retry-driver",
        check_status=lambda _project_id: {
            "status": "RUNNING",
            "message": "任务已完成，获取结果中...",
            "preserve_retry_count": True,
        },
    )
    monkeypatch.setattr(
        "task.visual_drivers.VideoDriverFactory.create_driver_by_type",
        lambda *_args, **_kwargs: driver,
    )
    monkeypatch.setattr(visual_task.AIToolsLogModel, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        visual_task.TasksModel,
        "get_by_task_id",
        lambda _task_id: SimpleNamespace(try_count=29),
    )
    updates = []
    monkeypatch.setattr(
        visual_task.TasksModel,
        "update_by_task_id",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    ai_tool = SimpleNamespace(
        id=200,
        project_id="project-200",
        type=-1,
        user_id=1,
        implementation=None,
    )
    result = asyncio.run(visual_task._check_task_status(ai_tool))

    assert result == visual_task.PROCESS_RESULT_IN_FLIGHT
    assert len(updates) == 1
    args, kwargs = updates[0]
    assert args == (200,)
    assert "next_trigger" in kwargs
    assert "try_count" not in kwargs
