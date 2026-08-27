# -*- coding: utf-8 -*-
"""
f668 回归测试：孤儿任务恢复的时间宽限保护。

背景：sync_mode 任务成功完成后，check_results 存在「清理 _futures（内存）→
写终态（DB）」的时序窗口。窗口内任务呈现 PROCESSING + 无 project_id + 不在
同步执行器 的组合，与子进程崩溃无法区分，孤儿恢复若立即重置会重复提交、
重复计费。宽限逻辑要求 ai_tools.update_time 距今超过阈值才允许重置。
"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from task import visual_task


def _make_ai_tool(update_time):
    ai_tool = MagicMock()
    ai_tool.id = 200
    ai_tool.project_id = None
    ai_tool.type = 25
    ai_tool.user_id = 1
    ai_tool.update_time = update_time
    return ai_tool


def _patch_orphan_dependencies(monkeypatch, grace_seconds=300):
    """屏蔽 _check_task_status 的外部依赖：executor 报告任务不在运行（模拟竞态窗口）。"""
    fake_executor = MagicMock()
    fake_executor.is_task_running.return_value = False
    monkeypatch.setattr(
        "task.sync_task_executor.get_sync_task_executor", lambda: fake_executor
    )
    monkeypatch.setattr(
        visual_task, "get_sync_orphan_grace_seconds", lambda: grace_seconds
    )
    updates = []

    def _record_update(*args, **kwargs):
        updates.append((args, kwargs))

    monkeypatch.setattr(visual_task.AIToolsModel, "update", staticmethod(_record_update))
    monkeypatch.setattr(
        visual_task.TasksModel, "update_by_task_id", staticmethod(_record_update)
    )
    return updates


def test_orphan_reset_skipped_within_grace_window(monkeypatch):
    """update_time 距今 30s（< 300s 宽限）：不得重置，返回 True 避免重试计数。"""
    updates = _patch_orphan_dependencies(monkeypatch)
    ai_tool = _make_ai_tool(datetime.now() - timedelta(seconds=30))

    result = asyncio.run(visual_task._check_task_status(ai_tool))

    assert result is True
    assert updates == []


def test_orphan_reset_still_fires_after_grace_expires(monkeypatch):
    """update_time 距今 400s（> 300s 宽限）：真孤儿（子进程崩溃）仍走原重置逻辑。"""
    updates = _patch_orphan_dependencies(monkeypatch)
    ai_tool = _make_ai_tool(datetime.now() - timedelta(seconds=400))

    result = asyncio.run(visual_task._check_task_status(ai_tool))

    assert result is True
    assert len(updates) == 2  # AIToolsModel.update + TasksModel.update_by_task_id
    assert updates[0][1].get("status") == visual_task.AI_TOOL_STATUS_PENDING


def test_orphan_reset_immediate_when_grace_disabled(monkeypatch):
    """宽限配置为 0（禁用）：恢复旧行为，立即重置。"""
    updates = _patch_orphan_dependencies(monkeypatch, grace_seconds=0)
    ai_tool = _make_ai_tool(datetime.now() - timedelta(seconds=1))

    result = asyncio.run(visual_task._check_task_status(ai_tool))

    assert result is True
    assert len(updates) == 2


def test_orphan_reset_fires_when_update_time_missing(monkeypatch):
    """update_time 为空（历史脏数据）：无法判定活跃时间，保守走原重置逻辑。"""
    updates = _patch_orphan_dependencies(monkeypatch)
    ai_tool = _make_ai_tool(None)

    result = asyncio.run(visual_task._check_task_status(ai_tool))

    assert result is True
    assert len(updates) == 2
