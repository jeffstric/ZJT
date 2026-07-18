import asyncio
from types import SimpleNamespace

import pytest

from config.constant import ScriptSplitConstants
from task import script_split_task as worker


def _task(task_id=81, status="generating", worker_id="host-1-claim-a"):
    return SimpleNamespace(id=task_id, status=status, worker_id=worker_id)


def test_lease_heartbeat_renews_with_current_claim_owner(monkeypatch):
    calls = []
    monkeypatch.setattr(ScriptSplitConstants, "LEASE_RENEW_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(ScriptSplitConstants, "LEASE_RENEW_DB_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(
        worker.ScriptSplitTaskModel,
        "renew_lease",
        staticmethod(lambda task_id, owner, seconds: calls.append((task_id, owner, seconds)) or True),
    )

    async def scenario():
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(worker._lease_heartbeat(81, "owner-a", stop))
        await asyncio.sleep(0.13)
        stop.set()
        await heartbeat

    asyncio.run(scenario())

    assert calls
    assert all(call == (81, "owner-a", ScriptSplitConstants.TASK_LEASE_SECONDS) for call in calls)


def test_lease_heartbeat_rejects_db_timeout_not_below_interval(monkeypatch):
    monkeypatch.setattr(ScriptSplitConstants, "LEASE_RENEW_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(ScriptSplitConstants, "LEASE_RENEW_DB_TIMEOUT_SECONDS", 0.02)

    async def scenario():
        with pytest.raises(worker.LeaseLostError, match="db timeout"):
            await asyncio.wait_for(
                worker._lease_heartbeat(81, "owner-a", asyncio.Event()),
                timeout=0.1,
            )

    asyncio.run(scenario())


def test_claimed_step_reclaims_stale_segments_once_before_advancing(monkeypatch):
    task = _task()
    calls = {"reclaim": [], "advance": [], "release": []}
    monkeypatch.setattr(worker.ScriptSplitTaskModel, "claim_next_task", staticmethod(lambda _lease: task))
    monkeypatch.setattr(
        worker.ScriptSplitSegmentModel,
        "reclaim_stale_generating",
        staticmethod(lambda task_id, owner, limit: (
            calls["reclaim"].append((task_id, owner, limit))
            or {"lease_owned": True, "reclaimed_count": 1, "exhausted_segment_indexes": []}
        )),
    )
    monkeypatch.setattr(
        worker.ScriptSplitTaskModel,
        "release_lease",
        staticmethod(lambda task_id, owner: calls["release"].append((task_id, owner)) or True),
    )

    async def advance(claimed_task):
        calls["advance"].append(claimed_task.id)

    monkeypatch.setattr(worker, "_advance_one_step", advance)

    asyncio.run(worker.process_script_split_tasks())

    assert calls["reclaim"] == [(81, "host-1-claim-a", ScriptSplitConstants.STALE_SEGMENT_MAX_RECOVERIES)]
    assert calls["advance"] == [81]
    assert calls["release"] == [(81, "host-1-claim-a")]


def test_repeated_stale_segment_pauses_before_running_engine(monkeypatch):
    task = _task()
    updates = []
    advanced = []
    monkeypatch.setattr(worker.ScriptSplitTaskModel, "claim_next_task", staticmethod(lambda _lease: task))
    monkeypatch.setattr(
        worker.ScriptSplitSegmentModel,
        "reclaim_stale_generating",
        staticmethod(lambda *_args: {
            "lease_owned": True,
            "reclaimed_count": 1,
            "exhausted_segment_indexes": [2],
        }),
    )
    monkeypatch.setattr(
        worker.ScriptSplitTaskModel,
        "update_status",
        staticmethod(lambda *args, **kwargs: updates.append((args, kwargs))),
    )
    monkeypatch.setattr(worker.ScriptSplitTaskModel, "release_lease", staticmethod(lambda *_args: True))

    async def advance(_task):
        advanced.append(True)

    monkeypatch.setattr(worker, "_advance_one_step", advance)

    asyncio.run(worker.process_script_split_tasks())

    assert advanced == []
    assert updates[-1][0][1] == ScriptSplitConstants.STATUS_PAUSED
    assert updates[-1][1]["last_error_code"] == "segment_repeatedly_interrupted"


def test_lost_lease_cancels_step_without_overwriting_task_status(monkeypatch):
    task = _task()
    updates = []
    cancelled = []
    monkeypatch.setattr(ScriptSplitConstants, "LEASE_RENEW_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(ScriptSplitConstants, "LEASE_RENEW_DB_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(worker.ScriptSplitTaskModel, "claim_next_task", staticmethod(lambda _lease: task))
    monkeypatch.setattr(
        worker.ScriptSplitSegmentModel,
        "reclaim_stale_generating",
        staticmethod(lambda *_args: {
            "lease_owned": True,
            "reclaimed_count": 0,
            "exhausted_segment_indexes": [],
        }),
    )
    monkeypatch.setattr(worker.ScriptSplitTaskModel, "renew_lease", staticmethod(lambda *_args: False))
    monkeypatch.setattr(worker.ScriptSplitTaskModel, "release_lease", staticmethod(lambda *_args: False))
    monkeypatch.setattr(
        worker.ScriptSplitTaskModel,
        "update_status",
        staticmethod(lambda *args, **kwargs: updates.append((args, kwargs))),
    )

    async def slow_step(_task):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(worker, "_advance_one_step", slow_step)

    asyncio.run(worker.process_script_split_tasks())

    assert cancelled == [True]
    assert updates == []
