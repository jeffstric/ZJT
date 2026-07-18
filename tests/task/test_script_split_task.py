import asyncio

import pytest

from config.constant import ScriptSplitConstants
from model.script_split_task import ScriptSplitTask
from task import script_split_task


def test_legacy_merging_state_is_not_routed():
    task = ScriptSplitTask(id=20, status=ScriptSplitConstants.STATUS_MERGING)

    with pytest.raises(script_split_task.engine.EngineError) as exc_info:
        asyncio.run(script_split_task._advance_one_step(task))

    assert exc_info.value.code == "invalid_task_state"


def test_invalid_checkpoint_error_becomes_terminal_failed(monkeypatch):
    task = ScriptSplitTask(
        id=21,
        status=ScriptSplitConstants.STATUS_GENERATING,
        worker_id="test-host-claim-21",
    )
    updates = []
    releases = []

    async def fail_step(_task):
        raise script_split_task.engine.EngineError(
            "invalid_segment_checkpoint_state", "broken checkpoints"
        )

    monkeypatch.setattr(
        script_split_task.ScriptSplitTaskModel,
        "claim_next_task",
        lambda _lease: task,
    )
    monkeypatch.setattr(script_split_task, "_advance_one_step", fail_step)
    monkeypatch.setattr(
        script_split_task.ScriptSplitSegmentModel,
        "reclaim_stale_generating",
        lambda *_args: {
            "lease_owned": True,
            "reclaimed_count": 0,
            "exhausted_segment_indexes": [],
        },
    )
    monkeypatch.setattr(
        script_split_task.ScriptSplitTaskModel,
        "update_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )
    monkeypatch.setattr(
        script_split_task.ScriptSplitTaskModel,
        "release_lease",
        lambda task_id, worker_id: releases.append((task_id, worker_id)),
    )

    asyncio.run(script_split_task.process_script_split_tasks())

    assert updates[-1][0][1] == ScriptSplitConstants.STATUS_FAILED
    assert updates[-1][1]["last_error_code"] == "invalid_segment_checkpoint_state"
    assert releases == [(21, "test-host-claim-21")]


def test_step_watchdog_timeout_becomes_resumable_paused(monkeypatch):
    task = ScriptSplitTask(
        id=22,
        status=ScriptSplitConstants.STATUS_GENERATING,
        worker_id="test-host-claim-22",
    )
    updates = []
    releases = []

    async def timeout_step(_task):
        raise asyncio.TimeoutError

    monkeypatch.setattr(
        script_split_task.ScriptSplitTaskModel,
        "claim_next_task",
        lambda _lease: task,
    )
    monkeypatch.setattr(script_split_task, "_advance_one_step", timeout_step)
    monkeypatch.setattr(
        script_split_task.ScriptSplitSegmentModel,
        "reclaim_stale_generating",
        lambda *_args: {
            "lease_owned": True,
            "reclaimed_count": 0,
            "exhausted_segment_indexes": [],
        },
    )
    monkeypatch.setattr(
        script_split_task.ScriptSplitTaskModel,
        "update_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )
    monkeypatch.setattr(
        script_split_task.ScriptSplitTaskModel,
        "release_lease",
        lambda task_id, worker_id: releases.append((task_id, worker_id)),
    )

    asyncio.run(script_split_task.process_script_split_tasks())

    assert updates[-1][0][1] == ScriptSplitConstants.STATUS_PAUSED
    assert updates[-1][1]["last_error_code"] == "step_watchdog_timeout"
    assert "点击继续" in updates[-1][1]["last_error_message"]
    assert releases == [(22, "test-host-claim-22")]
