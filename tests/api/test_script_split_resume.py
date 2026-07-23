import asyncio

import pytest

from config.constant import ScriptSplitConstants
from model.script_split_segment import ScriptSplitSegment
from model.script_split_task import ScriptSplitTask
from api import script_split
from api.script_split import (
    _resume_target_state,
    _validate_world_scene_precondition,
    ScriptSplitPreconditionError,
)


def test_resume_targets_publishing_when_final_result_exists():
    task = ScriptSplitTask(
        status=ScriptSplitConstants.STATUS_PAUSED,
        phase="publishing",
        segment_plan_json={"segments": [{}]},
        final_result_json={"shot_groups": []},
    )

    assert _resume_target_state(task) == ScriptSplitConstants.STATUS_PUBLISHING


def test_request_config_normalizes_sequence_mode():
    assert script_split._normalize_request_config({})["sequence_mode"] == "balanced"
    assert script_split._normalize_request_config({"sequence_mode": " QUALITY "})["sequence_mode"] == "quality"


def test_request_config_rejects_unknown_sequence_mode():
    try:
        script_split._normalize_request_config({"sequence_mode": "turbo"})
    except ValueError as exc:
        assert "sequence_mode" in str(exc)
    else:
        raise AssertionError("unknown sequence_mode should be rejected")


def _patch_location_counts(monkeypatch, total, with_image):
    monkeypatch.setattr(
        script_split.LocationModel, "count_by_world", lambda wid: total
    )
    monkeypatch.setattr(
        script_split.LocationModel,
        "count_with_image_by_world",
        lambda wid: with_image,
    )


def test_precondition_skips_when_world_id_missing(monkeypatch):
    """world_id 缺失（如 cli 来源）时跳过校验，且不查 DB。"""
    def boom(*args, **kwargs):
        raise AssertionError("should not query DB when world_id missing")
    monkeypatch.setattr(script_split.LocationModel, "count_by_world", boom)
    monkeypatch.setattr(script_split.LocationModel, "count_with_image_by_world", boom)

    asyncio.run(_validate_world_scene_precondition(None))
    asyncio.run(_validate_world_scene_precondition(""))


def test_precondition_raises_when_world_has_no_scene(monkeypatch):
    _patch_location_counts(monkeypatch, total=0, with_image=0)
    with pytest.raises(ScriptSplitPreconditionError) as exc:
        asyncio.run(_validate_world_scene_precondition(252))
    assert exc.value.code == "world_no_scene"


def test_precondition_raises_when_no_scene_has_image(monkeypatch):
    """有场景但全部无参考图 → 阻止（world_no_scene_image）。"""
    _patch_location_counts(monkeypatch, total=5, with_image=0)
    with pytest.raises(ScriptSplitPreconditionError) as exc:
        asyncio.run(_validate_world_scene_precondition(246))
    assert exc.value.code == "world_no_scene_image"


def test_precondition_passes_when_world_has_imaged_scene(monkeypatch):
    """至少 1 个场景有参考图 → 放行（不抛异常）。"""
    _patch_location_counts(monkeypatch, total=5, with_image=2)
    asyncio.run(_validate_world_scene_precondition(246))


def test_character_contract_pause_exposes_sanitized_validation_details(monkeypatch):
    task = ScriptSplitTask(
        id=22,
        user_id=7,
        status=ScriptSplitConstants.STATUS_PAUSED,
        last_error_code=ScriptSplitConstants.ERROR_CHARACTER_PROMPT_CONTRACT_INVALID,
        last_error_message="角色提示词硬校验失败",
    )
    segment = ScriptSplitSegment(
        task_id=22,
        segment_index=1,
        validation_errors=[{
            "code": "character_prompt_name_invalid",
            "message": "必须使用奶昔_Milkshake",
            "field": "opening_frame_description",
            "actual_name": "奶昔",
            "expected_name": "奶昔_Milkshake",
            "_hard_gate": True,
            "_hard_gate_type": "character_prompt",
            "_character_hard_round": 3,
        }],
    )
    monkeypatch.setattr(
        script_split.ScriptSplitSegmentModel,
        "get_first_uncompleted",
        lambda _task_id: segment,
    )

    data = asyncio.run(script_split._public_task_status(task))

    assert data["validation_errors"][0]["expected_name"] == "奶昔_Milkshake"
    assert data["validation_errors"][0]["actual_name"] == "奶昔"
    assert "_character_hard_round" not in data["validation_errors"][0]


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


def test_create_task_replaces_client_character_contract_with_server_snapshot(monkeypatch):
    captured = {}
    server_snapshot = {
        "version": 1,
        "world_id": 823,
        "characters": [{
            "character_db_id": 17,
            "canonical_name": "奶昔_Milkshake",
        }],
    }

    async def no_precondition(_world_id):
        return None

    def fake_active_key(*_args):
        captured["active_key_config"] = dict(_args[-1])
        return "safe-key"

    def fake_create(*args):
        captured["persisted_config"] = args[7]
        return 91, True

    monkeypatch.setattr(script_split, "_validate_world_scene_precondition", no_precondition)
    monkeypatch.setattr(script_split, "compute_active_key", fake_active_key)
    monkeypatch.setattr(
        script_split,
        "build_character_contract_snapshot",
        lambda world_id: server_snapshot if world_id == 823 else None,
    )
    monkeypatch.setattr(
        script_split.ScriptSplitTaskModel,
        "create_or_get_active",
        fake_create,
    )

    task_id, is_new = asyncio.run(script_split.create_split_task(
        user_id=7,
        source_type=ScriptSplitConstants.SOURCE_TYPE_STORYBOARD,
        source_id=9,
        source_node_key=None,
        script_content="测试剧本",
        request_config={
            "world_id": 823,
            "_character_contract": {
                "characters": [{"canonical_name": "奶昔"}],
            },
        },
    ))

    assert (task_id, is_new) == (91, True)
    assert "_character_contract" not in captured["active_key_config"]
    assert captured["persisted_config"]["_character_contract"] == server_snapshot


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
