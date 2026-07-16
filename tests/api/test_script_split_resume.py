import asyncio

from config.constant import ScriptSplitConstants
from model.script_split_segment import ScriptSplitSegment
from model.script_split_task import ScriptSplitTask
from api import script_split
from api.script_split import _resume_target_state


def test_resume_targets_publishing_when_final_result_exists():
    task = ScriptSplitTask(
        status=ScriptSplitConstants.STATUS_PAUSED,
        phase="publishing",
        segment_plan_json={"segments": [{}]},
        final_result_json={"shot_groups": []},
    )

    assert _resume_target_state(task) == ScriptSplitConstants.STATUS_PUBLISHING


def test_request_config_normalizes_sequence_mode():
    assert script_split._normalize_request_config({})["sequence_mode"] == "speed"
    assert script_split._normalize_request_config({"sequence_mode": " QUALITY "})["sequence_mode"] == "quality"


def test_request_config_rejects_unknown_sequence_mode():
    try:
        script_split._normalize_request_config({"sequence_mode": "turbo"})
    except ValueError as exc:
        assert "sequence_mode" in str(exc)
    else:
        raise AssertionError("unknown sequence_mode should be rejected")


def test_resume_targets_generating_when_plan_exists():
    task = ScriptSplitTask(
        status=ScriptSplitConstants.STATUS_PAUSED,
        phase="segment_generation",
        segment_plan_json={"segments": [{}]},
    )

    assert _resume_target_state(task) == ScriptSplitConstants.STATUS_GENERATING


def test_resume_targets_queued_without_plan():
    task = ScriptSplitTask(
        status=ScriptSplitConstants.STATUS_PAUSED,
        phase="planning",
    )

    assert _resume_target_state(task) == ScriptSplitConstants.STATUS_QUEUED


def test_resume_endpoint_restores_planned_task_to_generating(monkeypatch):
    task = ScriptSplitTask(
        id=23,
        user_id=7,
        status=ScriptSplitConstants.STATUS_PAUSED,
        phase="segment_generation",
        progress=42,
        segment_plan_json={"segments": [{}]},
    )
    updates = []
    reset_budgets = []

    async def fake_get_task(_task_id):
        return task

    monkeypatch.setattr(script_split, "_get_task_async", fake_get_task)
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "update_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )
    monkeypatch.setattr(
        script_split.ScriptSplitSegmentModel,
        "reset_retry_budget",
        lambda task_id: reset_budgets.append(task_id),
        raising=False,
    )

    response = asyncio.run(script_split.resume_task(
        task_id=23,
        request=None,
        auth_token=None,
        user_id=7,
    ))

    assert response["data"]["status"] == ScriptSplitConstants.STATUS_GENERATING
    assert reset_budgets == [23]
    assert updates == [
        ((23, ScriptSplitConstants.STATUS_GENERATING), {
            "phase": "segment_generation",
            "progress": 42,
            "clear_error": True,
        })
    ]


def test_resume_qc_exhausted_task_preserves_round_for_forced_accept(monkeypatch):
    task = ScriptSplitTask(
        id=24,
        user_id=7,
        status=ScriptSplitConstants.STATUS_PAUSED,
        phase="segment_generation",
        progress=42,
        segment_plan_json={"segments": [{}]},
        last_error_code="segment_qc_failed",
    )
    updates = []
    reset_budgets = []

    async def fake_get_task(_task_id):
        return task

    monkeypatch.setattr(script_split, "_get_task_async", fake_get_task)
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "update_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )
    monkeypatch.setattr(
        script_split.ScriptSplitSegmentModel,
        "reset_retry_budget",
        lambda task_id: reset_budgets.append(task_id),
        raising=False,
    )

    response = asyncio.run(script_split.resume_task(
        task_id=24,
        request=None,
        auth_token=None,
        user_id=7,
    ))

    assert response["data"]["status"] == ScriptSplitConstants.STATUS_GENERATING
    assert reset_budgets == []
    assert updates == [
        ((24, ScriptSplitConstants.STATUS_GENERATING), {
            "phase": "segment_generation",
            "progress": 42,
            "clear_error": True,
        })
    ]


def test_resume_retry_exhausted_task_preserves_budget_when_candidate_exists(monkeypatch):
    task = ScriptSplitTask(
        id=25,
        user_id=7,
        status=ScriptSplitConstants.STATUS_PAUSED,
        phase="segment_generation",
        progress=42,
        segment_plan_json={"segments": [{}]},
        last_error_code="segment_max_retries",
    )
    segment = ScriptSplitSegment(
        task_id=25,
        segment_index=1,
        parsed_result_json={"shot_groups": [{"shots": []}]},
    )
    reset_budgets = []

    async def fake_get_task(_task_id):
        return task

    monkeypatch.setattr(script_split, "_get_task_async", fake_get_task)
    monkeypatch.setattr(
        script_split.ScriptSplitSegmentModel,
        "get_first_uncompleted",
        lambda _task_id: segment,
    )
    monkeypatch.setattr(
        script_split.ScriptSplitSegmentModel,
        "reset_retry_budget",
        lambda task_id: reset_budgets.append(task_id),
    )
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "update_status",
        lambda *args, **kwargs: None,
    )

    response = asyncio.run(script_split.resume_task(
        task_id=25,
        request=None,
        auth_token=None,
        user_id=7,
    ))

    assert response["data"]["status"] == ScriptSplitConstants.STATUS_GENERATING
    assert reset_budgets == []


def test_duplicate_submission_auto_resumes_paused_task(monkeypatch):
    paused_task = ScriptSplitTask(
        id=31,
        user_id=7,
        status=ScriptSplitConstants.STATUS_PAUSED,
        phase="segment_generation",
        progress=36,
        segment_plan_json={"segments": [{}]},
    )
    updates = []
    saved_fields = []
    reset_budgets = []

    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "create_or_get_active",
        lambda *_args, **_kwargs: (31, False),
    )
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "get_by_id",
        lambda _task_id: paused_task,
    )
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "save_field",
        lambda *args, **kwargs: saved_fields.append((args, kwargs)),
    )
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "update_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )
    monkeypatch.setattr(
        script_split.ScriptSplitSegmentModel,
        "reset_retry_budget",
        lambda task_id: reset_budgets.append(task_id),
        raising=False,
    )

    task_id, is_new = asyncio.run(script_split.create_split_task(
        user_id=7,
        source_type=ScriptSplitConstants.SOURCE_TYPE_STORYBOARD,
        source_id=9,
        source_node_key=None,
        script_content="同一份剧本",
        request_config={"model": "test-model"},
        auth_token="fresh-token",
    ))

    assert (task_id, is_new) == (31, False)
    assert reset_budgets == [31]
    assert saved_fields == [((31,), {"auth_token": "fresh-token"})]
    assert updates == [
        ((31, ScriptSplitConstants.STATUS_GENERATING), {
            "phase": "segment_generation",
            "progress": 36,
            "clear_error": True,
        })
    ]


def test_duplicate_submission_does_not_restart_running_task(monkeypatch):
    running_task = ScriptSplitTask(
        id=32,
        user_id=7,
        status=ScriptSplitConstants.STATUS_GENERATING,
        phase="segment_generation",
        segment_plan_json={"segments": [{}]},
    )
    updates = []

    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "create_or_get_active",
        lambda *_args, **_kwargs: (32, False),
    )
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "get_by_id",
        lambda _task_id: running_task,
    )
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "update_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    task_id, is_new = asyncio.run(script_split.create_split_task(
        user_id=7,
        source_type=ScriptSplitConstants.SOURCE_TYPE_STORYBOARD,
        source_id=9,
        source_node_key=None,
        script_content="同一份剧本",
        request_config={"model": "test-model"},
    ))

    assert (task_id, is_new) == (32, False)
    assert updates == []


def test_duplicate_submission_refreshes_token_and_resumes_waiting_auth(monkeypatch):
    waiting_task = ScriptSplitTask(
        id=33,
        user_id=7,
        status=ScriptSplitConstants.STATUS_WAITING_AUTH,
        phase="planning",
        progress=8,
    )
    updates = []
    saved_fields = []

    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "create_or_get_active",
        lambda *_args, **_kwargs: (33, False),
    )
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "get_by_id",
        lambda _task_id: waiting_task,
    )
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "save_field",
        lambda *args, **kwargs: saved_fields.append((args, kwargs)),
    )
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "update_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )

    task_id, is_new = asyncio.run(script_split.create_split_task(
        user_id=7,
        source_type=ScriptSplitConstants.SOURCE_TYPE_STORYBOARD,
        source_id=9,
        source_node_key=None,
        script_content="同一份剧本",
        request_config={"model": "test-model"},
        auth_token="renewed-token",
    ))

    assert (task_id, is_new) == (33, False)
    assert saved_fields == [((33,), {"auth_token": "renewed-token"})]
    assert updates == [
        ((33, ScriptSplitConstants.STATUS_QUEUED), {
            "phase": "queued",
            "progress": 5,
            "clear_error": True,
        })
    ]
