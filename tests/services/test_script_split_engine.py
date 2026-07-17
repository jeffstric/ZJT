import asyncio
from types import SimpleNamespace

import pytest

from llm import script_parser
from llm import script_segment_planner
from llm.script_split_qc_agent import QcIssue, QcReport
from config.constant import ScriptSplitConstants
from model.script_split_segment import ScriptSplitSegment
from model.script_split_task import ScriptSplitTask
from services import script_split_engine


PLAN_ANCHORS = [
    {
        "block_id": "block_0001",
        "start_line": 1,
        "end_line": 1,
        "summary": "开场",
        "content": "INT. ROOM - DAY",
    }
]


def _segment_plan():
    return {
        "schema_version": 1,
        "segments": [
            {
                "segment_id": "seg_0001",
                "block_ids": ["block_0001"],
                "title": "开场",
                "summary": "角色进入房间",
                "continuity_notes": "角色站在门边",
            }
        ],
    }


def _planning_task(**overrides):
    values = {
        "id": 81,
        "script_content": "INT. ROOM - DAY",
        "request_config": {},
        "auth_token": "secret-token",
        "plan_revision": 0,
    }
    values.update(overrides)
    return ScriptSplitTask(**values)


def _disable_plan_persistence(monkeypatch):
    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "update_plan",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "update_status",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "replace_all",
        lambda *_args, **_kwargs: None,
    )


async def _empty_db_locations(_config=None):
    return []


def _mock_db_locations(monkeypatch, locations=None):
    result = list(locations or [])

    async def _loader(_config=None):
        return result

    monkeypatch.setattr(
        script_split_engine,
        "_load_current_db_locations",
        _loader,
    )


def test_step_plan_correlates_retry_attempts_and_validation_logs(monkeypatch):
    task = _planning_task()
    plan_results = iter([{}, _segment_plan()])
    validation_results = iter([
        (False, [{"code": "segment_gap", "message": "未覆盖全部 block"}]),
        (True, []),
    ])
    plan_calls = []
    validation_logs = []

    async def fake_plan_segments(**kwargs):
        plan_calls.append(kwargs)
        return next(plan_results), "stop"

    async def fake_write_validation(context, payload):
        validation_logs.append((context, payload))

    monkeypatch.setattr(script_segment_planner, "plan_segments", fake_plan_segments)
    monkeypatch.setattr(
        script_segment_planner,
        "write_plan_validation_log",
        fake_write_validation,
    )
    monkeypatch.setattr(script_split_engine, "anchorize_script", lambda _script: PLAN_ANCHORS)
    monkeypatch.setattr(script_split_engine, "_is_cancelled", lambda _task_id: False)
    _mock_db_locations(monkeypatch, [])
    monkeypatch.setattr(
        script_split_engine,
        "validate_segment_plan",
        lambda _plan, _anchors: next(validation_results),
    )
    monkeypatch.setattr(
        script_split_engine,
        "plan_to_segments",
        lambda _plan, _anchors: [{"segment_index": 1}],
    )
    _disable_plan_persistence(monkeypatch)

    asyncio.run(script_split_engine.step_plan(task))

    assert [call["log_context"].attempt for call in plan_calls] == [1, 2]
    assert [call["log_context"].plan_kind for call in plan_calls] == ["initial", "initial"]
    assert "segment_gap" in plan_calls[1]["feedback"]
    assert [payload["passed"] for _, payload in validation_logs] == [False, True]
    assert validation_logs[0][1]["errors"][0]["code"] == "segment_gap"
    assert validation_logs[1][1]["segments"][0]["segment_id"] == "seg_0001"


def test_step_plan_logs_timeout_without_auth_token(monkeypatch):
    task = _planning_task()
    validation_logs = []

    async def timeout_plan(**_kwargs):
        raise asyncio.TimeoutError

    async def fake_write_validation(_context, payload):
        validation_logs.append(payload)

    monkeypatch.setattr(script_segment_planner, "plan_segments", timeout_plan)
    monkeypatch.setattr(
        script_segment_planner,
        "write_plan_validation_log",
        fake_write_validation,
    )
    monkeypatch.setattr(script_split_engine, "anchorize_script", lambda _script: PLAN_ANCHORS)
    monkeypatch.setattr(script_split_engine, "_is_cancelled", lambda _task_id: False)
    _mock_db_locations(monkeypatch, [])

    with pytest.raises(script_split_engine.EngineError) as exc_info:
        asyncio.run(script_split_engine.step_plan(task))

    assert exc_info.value.code == "plan_timeout"
    assert validation_logs[0]["errors"][0]["code"] == "plan_timeout"
    assert "secret-token" not in str(validation_logs)


def test_step_plan_uses_strategy_prompt_and_persists_compiled_registry(monkeypatch):
    task = _planning_task(request_config={"sequence_mode": "quality"})
    raw_plan = _segment_plan()
    compiled_plan = dict(
        raw_plan,
        compiled_registry={
            "characters": [],
            "locations": [],
            "props": [],
            "spatial_world": {"space_units": []},
        },
    )
    plan_calls = []
    saved_fields = []

    class FakeStrategy:
        def build_planning_prompt(self, anchors, max_output_tokens):
            assert anchors == PLAN_ANCHORS
            assert max_output_tokens > 0
            return "enterprise-quality-prompt"

        def compile_plan(self, plan, anchors, db_locations=None):
            assert plan == raw_plan
            assert anchors == PLAN_ANCHORS
            assert db_locations == []
            return compiled_plan

    async def fake_plan_segments(**kwargs):
        plan_calls.append(kwargs)
        return raw_plan, "stop"

    async def fake_write_validation(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        script_split_engine,
        "get_script_split_strategy",
        lambda _mode: FakeStrategy(),
    )
    monkeypatch.setattr(script_segment_planner, "plan_segments", fake_plan_segments)
    monkeypatch.setattr(
        script_segment_planner,
        "write_plan_validation_log",
        fake_write_validation,
    )
    monkeypatch.setattr(script_split_engine, "anchorize_script", lambda _script: PLAN_ANCHORS)
    monkeypatch.setattr(script_split_engine, "_is_cancelled", lambda _task_id: False)
    _mock_db_locations(monkeypatch, [])
    monkeypatch.setattr(
        script_split_engine,
        "validate_segment_plan",
        lambda _plan, _anchors: (True, []),
    )
    monkeypatch.setattr(
        script_split_engine,
        "plan_to_segments",
        lambda plan, _anchors: [{"segment_index": 1}] if plan is compiled_plan else [],
    )
    _disable_plan_persistence(monkeypatch)
    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "save_field",
        lambda task_id, **fields: saved_fields.append((task_id, fields)),
    )

    asyncio.run(script_split_engine.step_plan(task))

    assert plan_calls[0]["prompt_override"] == "enterprise-quality-prompt"
    assert saved_fields == [(81, {"accepted_registry_json": compiled_plan["compiled_registry"]})]


def test_quality_parallel_batch_starts_multiple_segments_together(monkeypatch):
    task = ScriptSplitTask(id=91, total_segment_count=4)
    segments = [
        ScriptSplitSegment(
            task_id=91,
            segment_index=index,
            segment_id=f"seg_{index:04d}",
            source_content=f"segment {index}",
        )
        for index in range(1, 4)
    ]
    started = []
    release = asyncio.Event()
    saved_fields = []

    async def fake_generate(
        _task, _segment=None, _parallel_child=False, _all_segments=None,
    ):
        assert _parallel_child is True
        assert _all_segments == segments
        started.append(_segment.segment_index)
        if len(started) == 3:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=1)

    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_all",
        lambda _task_id: segments,
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_uncompleted",
        lambda _task_id, _limit: segments,
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "count_by_status",
        lambda *_args: 2,
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_first_uncompleted",
        lambda _task_id: segments[2],
    )
    monkeypatch.setattr(script_split_engine, "_is_cancelled", lambda _task_id: False)
    monkeypatch.setattr(script_split_engine, "step_generate_segment", fake_generate)
    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "save_field",
        lambda task_id, **fields: saved_fields.append((task_id, fields)),
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "update_status",
        lambda *_args, **_kwargs: None,
    )
    def fake_sync(task_id, total, previous_progress=None, current_segment_index=None):
        fields = {
            "completed_segment_count": 2,
            "current_segment_index": current_segment_index,
        }
        saved_fields.append((task_id, fields))
        return (50, 2)

    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "sync_generation_progress",
        fake_sync,
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "count_completed_segments",
        lambda _task_id: 2,
    )

    asyncio.run(script_split_engine._step_generate_parallel_batch(task, object()))

    assert started == [1, 2, 3]
    assert saved_fields[-1][1]["completed_segment_count"] == 2
    assert saved_fields[-1][1]["current_segment_index"] == 3


def test_parallel_forced_accept_preserves_planned_continuity_contract(monkeypatch):
    parsed = {
        "characters": [], "locations": [], "props": [],
        "spatial_world": {"space_units": []}, "shot_groups": [],
    }
    segment = ScriptSplitSegment(
        task_id=72,
        segment_index=2,
        segment_id="seg_0002",
        source_content="短剧本",
    )
    task = ScriptSplitTask(id=72, continuity_state_json={"legacy": True})
    continuity_in = {"location_id": "loc_001", "characters": ["char_001"]}
    forced_errors = [{"code": "QC_REJECTED", "_forced_accept": True}]
    saved = []

    class QualityStrategy:
        @staticmethod
        def build_segment_context(_plan, segment_id):
            assert segment_id == "seg_0002"
            return {"spatial_contract": {"continuity_in": continuity_in}}

    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_success",
        lambda *args, **kwargs: saved.append((args, kwargs)),
    )

    script_split_engine._complete_segment_result(
        task=task,
        seg=segment,
        parsed=parsed,
        strategy=QualityStrategy(),
        plan={"segments": []},
        registry=script_split_engine.AcceptedRegistry(),
        total=3,
        parallel_child=True,
        validation_errors=forced_errors,
    )

    assert len(saved) == 1
    assert saved[0][1]["continuity_in"] == continuity_in
    assert saved[0][1]["validation_errors"] == forced_errors


def test_segment_retry_passes_previous_parsed_result(monkeypatch):
    first_parsed = {
        "characters": [],
        "locations": [],
        "props": [],
        "spatial_world": {"space_units": []},
        "shot_groups": [],
        "attempt": 1,
    }
    second_parsed = {
        "characters": [],
        "locations": [],
        "props": [],
        "spatial_world": {"space_units": []},
        "shot_groups": [],
        "attempt": 2,
    }
    parse_calls = []
    parse_results = iter([first_parsed, second_parsed])

    async def fake_parse_script_to_shots(**kwargs):
        parse_calls.append(kwargs)
        return next(parse_results)

    validation_results = iter([
        (False, [{"code": "candidate_invalid", "message": "first failed"}]),
        (True, []),
    ])

    segment = ScriptSplitSegment(
        task_id=7,
        segment_index=1,
        segment_id="seg_0001",
        source_block_ids=["block_0001"],
        source_content="INT. ROOM - DAY",
    )
    task = ScriptSplitTask(
        id=7,
        request_config={"enable_qc": True, "qc_max_rounds": 2},
        accepted_registry_json={},
        continuity_state_json={},
        total_segment_count=1,
        completed_segment_count=0,
    )

    monkeypatch.setattr(script_parser, "parse_script_to_shots", fake_parse_script_to_shots)
    monkeypatch.setattr(script_split_engine, "_is_cancelled", lambda _task_id: False)
    _mock_db_locations(monkeypatch, [])
    monkeypatch.setattr(
        script_split_engine,
        "_validate_segment",
        lambda _parsed, _registry: next(validation_results),
    )
    async def passing_qc(**_kwargs):
        return QcReport(passed=True)
    monkeypatch.setattr(script_split_engine, "run_script_split_qc", passing_qc, raising=False)
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_first_uncompleted",
        lambda _task_id: segment,
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_completed",
        lambda _task_id: [],
    )
    for method_name in ("mark_generating", "save_success"):
        monkeypatch.setattr(
            script_split_engine.ScriptSplitSegmentModel,
            method_name,
            lambda *args, **kwargs: None,
        )
    def fake_save_failure(_task_id, _segment_index, errors, **kwargs):
        segment.attempt_count += 1
        segment.validation_errors = errors
        if kwargs.get("parsed_result") is not None:
            segment.parsed_result_json = kwargs["parsed_result"]

    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_failure",
        fake_save_failure,
    )
    for method_name in ("save_field", "increment_completed", "update_status", "sync_generation_progress"):
        monkeypatch.setattr(
            script_split_engine.ScriptSplitTaskModel,
            method_name,
            lambda *args, **kwargs: None,
        )

    asyncio.run(script_split_engine.step_generate_segment(task))

    assert len(parse_calls) == 1
    assert parse_calls[0]["previous_parsed_result"] is None
    assert segment.get_parsed_result() is first_parsed
    assert segment.get_validation_errors()[0]["code"] == "candidate_invalid"

    asyncio.run(script_split_engine.step_generate_segment(task))

    assert len(parse_calls) == 2
    assert parse_calls[1]["previous_parsed_result"] is first_parsed
    assert parse_calls[1]["qc_feedback"]["issues"][0]["code"] == "candidate_invalid"


def test_segment_llm_timeout_is_shorter_than_outer_step_watchdog():
    assert ScriptSplitConstants.LLM_CALL_TIMEOUT_SECONDS < (
        ScriptSplitConstants.WORKER_STEP_TIMEOUT_SECONDS
    )


def test_call_failure_does_not_consume_qc_round_budget(monkeypatch):
    parsed = {
        "characters": [], "locations": [], "props": [],
        "spatial_world": {"space_units": []}, "shot_groups": [],
    }
    segment = ScriptSplitSegment(
        task_id=71,
        segment_index=1,
        segment_id="seg_0001",
        source_content="短剧本",
        attempt_count=1,
        validation_errors=[{
            "code": "segment_call_failed",
            "severity": "error",
            "message": "network reset",
        }],
    )
    task = ScriptSplitTask(
        id=71,
        request_config={"enable_qc": True, "qc_max_rounds": 2},
        total_segment_count=1,
    )
    saved_failures = []

    async def fake_parse(**_kwargs):
        return parsed

    async def failing_qc(**_kwargs):
        return QcReport(passed=False, issues=[
            QcIssue(code="QC_REJECTED", severity="error", message="需要修复"),
        ])

    monkeypatch.setattr(script_parser, "parse_script_to_shots", fake_parse)
    monkeypatch.setattr(script_split_engine, "_validate_segment", lambda *_args: (True, []))
    monkeypatch.setattr(script_split_engine, "run_script_split_qc", failing_qc)
    _prepare_segment_generation_test(monkeypatch, task, segment)
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_failure",
        lambda *args, **kwargs: saved_failures.append((args, kwargs)),
    )

    asyncio.run(script_split_engine.step_generate_segment(task))

    assert len(saved_failures) == 1
    assert saved_failures[0][1]["parsed_result"] is parsed


def test_retry_exhaustion_reuses_last_parseable_candidate(monkeypatch):
    parsed = {
        "characters": [], "locations": [], "props": [],
        "spatial_world": {"space_units": []},
        "shot_groups": [{"group_id": "grp_001", "shots": [{"shot_id": "s001"}]}],
    }
    segment = ScriptSplitSegment(
        task_id=72,
        segment_index=1,
        segment_id="seg_0001",
        source_content="短剧本",
        attempt_count=3,
        parsed_result_json=parsed,
        validation_errors=[{
            "code": "segment_call_failed",
            "severity": "error",
            "message": "invalid JSON response",
            "_call_failure_count": 2,
            "_qc_round": 1,
        }],
    )
    task = ScriptSplitTask(
        id=72,
        request_config={"enable_qc": True, "qc_max_rounds": 2},
        accepted_registry_json={},
        continuity_state_json={},
        total_segment_count=1,
    )
    saved = []

    async def failing_parse(**_kwargs):
        raise ValueError("invalid control character")

    monkeypatch.setattr(script_parser, "parse_script_to_shots", failing_parse)
    _prepare_segment_generation_test(monkeypatch, task, segment)
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_success",
        lambda *args, **kwargs: saved.append((args, kwargs)),
    )

    asyncio.run(script_split_engine.step_generate_segment(task))

    assert len(saved) == 1
    assert saved[0][0][2] == parsed
    accepted_errors = saved[0][1]["validation_errors"]
    assert accepted_errors[0]["code"] == "segment_call_failed"
    assert accepted_errors[0]["_call_failure_count"] == 3
    assert accepted_errors[0]["_forced_accept"] is True


def _prepare_segment_generation_test(monkeypatch, task, segment):
    monkeypatch.setattr(script_split_engine, "_is_cancelled", lambda _task_id: False)
    _mock_db_locations(monkeypatch, [])
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_first_uncompleted",
        lambda _task_id: segment,
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_completed",
        lambda _task_id: [],
    )
    for method_name in ("mark_generating", "save_failure", "save_success"):
        monkeypatch.setattr(
            script_split_engine.ScriptSplitSegmentModel,
            method_name,
            lambda *args, **kwargs: None,
        )
    for method_name in (
        "save_field",
        "increment_completed",
        "update_status",
        "sync_generation_progress",
        "get_by_id",
    ):
        monkeypatch.setattr(
            script_split_engine.ScriptSplitTaskModel,
            method_name,
            lambda *args, **kwargs: None,
        )


def test_segment_generation_materializes_before_all_validators_and_qc(monkeypatch):
    events = []
    raw = {
        "characters": [], "locations": [], "props": [],
        "shot_groups": [{"shots": [{"shot_id": "shot_raw"}]}],
    }
    materialized = {
        "characters": [], "locations": [], "props": [],
        "shot_groups": [{"shots": [{"shot_id": "shot_materialized"}]}],
    }
    segment = ScriptSplitSegment(
        task_id=800, segment_index=1, segment_id="seg_0001",
        source_content="短剧本",
    )
    task = ScriptSplitTask(
        id=800,
        request_config={"enable_qc": True, "qc_max_rounds": 2},
        segment_plan_json={"segments": [{"segment_id": "seg_0001"}]},
        accepted_registry_json={}, continuity_state_json={},
        total_segment_count=1,
    )

    class Strategy:
        parallel_enabled = False

        def build_segment_context(self, _plan, _segment_id):
            return {"upstream_spatial_handoff": {"canonical_state": {}}}

        def materialize_segment_result(self, parsed, *_args):
            assert parsed is raw
            events.append("materialize")
            return SimpleNamespace(parsed=materialized)

        def validate_segment_result(self, parsed, *_args):
            assert parsed is materialized
            events.append("segment")
            return []

        def validate_cross_segment(self, parsed, *_args):
            assert parsed is materialized
            events.append("cross")
            return []

    async def fake_parse(**_kwargs):
        return raw

    async def fake_structure(parsed, _cfg, plan=None):
        assert parsed is materialized
        events.append("structure")
        return []

    async def fake_qc(**kwargs):
        assert kwargs["parsed"] is materialized
        events.append("qc")
        return []

    monkeypatch.setattr(script_parser, "parse_script_to_shots", fake_parse)
    monkeypatch.setattr(script_split_engine, "get_script_split_strategy", lambda _mode: Strategy())
    monkeypatch.setattr(script_split_engine, "_validate_segment_location_structure", fake_structure)
    monkeypatch.setattr(script_split_engine, "_run_enabled_segment_qc", fake_qc)
    _prepare_segment_generation_test(monkeypatch, task, segment)

    asyncio.run(script_split_engine.step_generate_segment(task))

    assert events == ["materialize", "structure", "segment", "cross", "qc"]


def test_disabled_qc_skips_local_and_agent_checks(monkeypatch):
    parsed = {
        "characters": [], "locations": [], "props": [],
        "spatial_world": {"space_units": []}, "shot_groups": [],
    }
    segment = ScriptSplitSegment(
        task_id=8, segment_index=1, segment_id="seg_0001",
        source_block_ids=["block_0001"], source_content="短剧本",
    )
    task = ScriptSplitTask(
        id=8, request_config={"enable_qc": False}, accepted_registry_json={},
        continuity_state_json={}, total_segment_count=1, completed_segment_count=0,
    )
    saved = []

    async def fake_parse(**_kwargs):
        return parsed

    def forbidden_local(*_args, **_kwargs):
        raise AssertionError("disabled QC must skip _validate_segment")

    async def forbidden_agent(**_kwargs):
        raise AssertionError("disabled QC must skip qc_agent")

    monkeypatch.setattr(script_parser, "parse_script_to_shots", fake_parse)
    monkeypatch.setattr(script_split_engine, "_validate_segment", forbidden_local)
    monkeypatch.setattr(script_split_engine, "run_script_split_qc", forbidden_agent, raising=False)
    _prepare_segment_generation_test(monkeypatch, task, segment)
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_success",
        lambda *args, **kwargs: saved.append((args, kwargs)),
    )

    asyncio.run(script_split_engine.step_generate_segment(task))

    assert len(saved) == 1
    assert saved[0][0][2] is parsed


def test_enabled_qc_combines_local_and_agent_issues(monkeypatch):
    parsed_results = [
        {"characters": [], "locations": [], "props": [],
         "spatial_world": {"space_units": []}, "shot_groups": [], "round": 1},
        {"characters": [], "locations": [], "props": [],
         "spatial_world": {"space_units": []}, "shot_groups": [], "round": 2},
    ]
    parse_calls = []
    local_results = iter([
        (False, [{"code": "entity_invalid", "severity": "error", "message": "实体错误"}]),
        (True, []),
    ])
    agent_results = iter([
        QcReport(passed=False, issues=[
            QcIssue(code="STRUCTURE_INVALID", severity="error", message="结构错误"),
        ]),
        QcReport(passed=True),
    ])
    agent_calls = []
    segment = ScriptSplitSegment(
        task_id=9, segment_index=1, segment_id="seg_0001",
        source_block_ids=["block_0001"], source_content="短剧本",
    )
    task = ScriptSplitTask(
        id=9, request_config={"enable_qc": True, "qc_max_rounds": 2},
        accepted_registry_json={}, continuity_state_json={},
        total_segment_count=1, completed_segment_count=0,
    )

    async def fake_parse(**kwargs):
        parse_calls.append(kwargs)
        return parsed_results[len(parse_calls) - 1]

    async def fake_agent(**kwargs):
        agent_calls.append(kwargs)
        return next(agent_results)

    monkeypatch.setattr(script_parser, "parse_script_to_shots", fake_parse)
    monkeypatch.setattr(
        script_split_engine, "_validate_segment",
        lambda _parsed, _registry: next(local_results),
    )
    monkeypatch.setattr(script_split_engine, "run_script_split_qc", fake_agent, raising=False)
    _prepare_segment_generation_test(monkeypatch, task, segment)
    def fake_save_failure(_task_id, _segment_index, errors, **kwargs):
        segment.attempt_count += 1
        segment.validation_errors = errors
        if kwargs.get("parsed_result") is not None:
            segment.parsed_result_json = kwargs["parsed_result"]

    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_failure",
        fake_save_failure,
    )

    asyncio.run(script_split_engine.step_generate_segment(task))

    assert len(agent_calls) == 1
    assert {issue["code"] for issue in segment.get_validation_errors()} == {
        "entity_invalid", "STRUCTURE_INVALID",
    }

    asyncio.run(script_split_engine.step_generate_segment(task))

    assert len(agent_calls) == 2
    issue_codes = {
        issue["code"] for issue in parse_calls[1]["qc_feedback"]["issues"]
    }
    assert issue_codes == {"entity_invalid", "STRUCTURE_INVALID"}
    assert parse_calls[1]["previous_parsed_result"] is parsed_results[0]


def test_qc_round_exhaustion_forces_latest_candidate_completion(monkeypatch):
    parsed = {
        "characters": [], "locations": [], "props": [],
        "spatial_world": {"space_units": []}, "shot_groups": [],
    }
    segment = ScriptSplitSegment(
        task_id=10, segment_index=1, segment_id="seg_0001",
        source_block_ids=["block_0001", "block_0002"], source_content="短剧本",
    )
    task = ScriptSplitTask(
        id=10, request_config={"enable_qc": True, "qc_max_rounds": 1},
        accepted_registry_json={}, continuity_state_json={}, plan_revision=0,
        total_segment_count=1, completed_segment_count=0,
    )

    async def fake_parse(**_kwargs):
        return parsed

    async def failing_agent(**_kwargs):
        return QcReport(passed=False, issues=[
            QcIssue(code="QC_REJECTED", severity="error", message="未通过"),
        ])

    monkeypatch.setattr(script_parser, "parse_script_to_shots", fake_parse)
    monkeypatch.setattr(script_split_engine, "_validate_segment", lambda *_args: (True, []))
    monkeypatch.setattr(script_split_engine, "run_script_split_qc", failing_agent)
    _prepare_segment_generation_test(monkeypatch, task, segment)
    saved = []
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_success",
        lambda *args, **kwargs: saved.append((args, kwargs)),
    )

    asyncio.run(script_split_engine.step_generate_segment(task))

    assert len(saved) == 1
    assert saved[0][0][2] is parsed
    accepted_errors = saved[0][1]["validation_errors"]
    assert accepted_errors[0]["code"] == "QC_REJECTED"
    assert accepted_errors[0]["_qc_round"] == 1
    assert accepted_errors[0]["_forced_accept"] is True


def test_existing_exhausted_qc_checkpoint_is_completed_without_llm(monkeypatch):
    parsed = {
        "characters": [], "locations": [], "props": [],
        "spatial_world": {"space_units": []}, "shot_groups": [],
    }
    segment = ScriptSplitSegment(
        task_id=13,
        segment_index=1,
        segment_id="seg_0001",
        source_block_ids=["block_0001"],
        source_content="短剧本",
        attempt_count=2,
        parsed_result_json=parsed,
        validation_errors=[{
            "code": "QC_REJECTED",
            "severity": "error",
            "message": "上一轮仍未通过",
            "_qc_round": 2,
            "_call_failure_count": 0,
        }],
    )
    task = ScriptSplitTask(
        id=13,
        request_config={"enable_qc": True, "qc_max_rounds": 2},
        accepted_registry_json={},
        continuity_state_json={},
        total_segment_count=1,
        completed_segment_count=0,
    )

    async def forbidden_parse(**_kwargs):
        raise AssertionError("QC 已耗尽且存在完整候选时不应再次调用 LLM")

    monkeypatch.setattr(script_parser, "parse_script_to_shots", forbidden_parse)
    _prepare_segment_generation_test(monkeypatch, task, segment)
    saved = []
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_success",
        lambda *args, **kwargs: saved.append((args, kwargs)),
    )

    asyncio.run(script_split_engine.step_generate_segment(task))

    assert len(saved) == 1
    assert saved[0][0][2] == parsed
    accepted_errors = saved[0][1]["validation_errors"]
    assert accepted_errors[0]["code"] == "QC_REJECTED"
    assert accepted_errors[0]["_forced_accept"] is True


def test_step_plan_retries_on_new_root_from_compile(monkeypatch):
    """L0：compile 因新顶层失败时进入规划重试，反馈含错误码。"""
    task = _planning_task(request_config={"sequence_mode": "quality"})
    plan_calls = []
    attempts = {"n": 0}

    class FakeStrategy:
        def build_planning_prompt(self, anchors, max_output_tokens):
            return "prompt"

        def compile_plan(self, plan, anchors, db_locations=None):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise ValueError(
                    "new_root_location_forbidden: 拆分流程不允许创建顶层场景：酒店办公室"
                )
            return dict(plan, compiled_registry={"locations": [], "characters": [], "props": []})

    async def fake_plan_segments(**kwargs):
        plan_calls.append(kwargs)
        return _segment_plan(), "stop"

    async def fake_write_validation(*_a, **_k):
        return None

    monkeypatch.setattr(
        script_split_engine,
        "get_script_split_strategy",
        lambda _mode: FakeStrategy(),
    )
    monkeypatch.setattr(script_segment_planner, "plan_segments", fake_plan_segments)
    monkeypatch.setattr(
        script_segment_planner, "write_plan_validation_log", fake_write_validation,
    )
    monkeypatch.setattr(script_split_engine, "anchorize_script", lambda _s: PLAN_ANCHORS)
    monkeypatch.setattr(script_split_engine, "_is_cancelled", lambda _t: False)
    _mock_db_locations(monkeypatch, [])
    monkeypatch.setattr(
        script_split_engine, "validate_segment_plan", lambda _p, _a: (True, []),
    )
    monkeypatch.setattr(
        script_split_engine, "plan_to_segments", lambda _p, _a: [{"segment_index": 1}],
    )
    _disable_plan_persistence(monkeypatch)
    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "save_field",
        lambda *a, **k: None,
    )

    asyncio.run(script_split_engine.step_plan(task))

    assert attempts["n"] == 2
    assert plan_calls[1].get("feedback")
    assert "new_root_location_forbidden" in plan_calls[1]["feedback"]


def test_segment_extended_hard_gate_on_space_unit_registry_new_root(monkeypatch):
    """L1：locations 合法但 space_unit 引用规划非法顶层 → hard pause。"""
    parsed = {
        "characters": [],
        "locations": [{
            "id": "loc_001",
            "name": "城南酒店大堂",
            "location_db_id": 565,
            "parent_id": None,
        }],
        "props": [],
        "spatial_world": {
            "space_units": [{
                "space_unit_id": "space_unit:office",
                "name": "酒店办公室",
                "owner_id": "loc_004",
                "location_ids": ["loc_004"],
            }]
        },
        "shot_groups": [],
    }
    plan = {
        "compiled_registry": {
            "locations": [
                {"id": "loc_001", "name": "城南酒店大堂", "location_db_id": 565},
                {
                    "id": "loc_004",
                    "name": "酒店办公室",
                    "location_db_id": None,
                    "parent_id": None,
                },
            ]
        }
    }
    segment = ScriptSplitSegment(
        task_id=201,
        segment_index=1,
        segment_id="seg_0001",
        source_content="短剧本",
    )
    task = ScriptSplitTask(
        id=201,
        request_config={"enable_qc": False, "world_id": 6},
        segment_plan_json=plan,
        accepted_registry_json={},
        continuity_state_json={},
        total_segment_count=1,
    )
    saved_failures = []

    async def fake_parse(**_kwargs):
        return parsed

    monkeypatch.setattr(script_parser, "parse_script_to_shots", fake_parse)
    _prepare_segment_generation_test(monkeypatch, task, segment)
    _mock_db_locations(monkeypatch, [
        {"id": 565, "name": "城南酒店大堂", "parent_id": None, "children": []},
    ])
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_failure",
        lambda *args, **kwargs: saved_failures.append((args, kwargs)),
    )

    with pytest.raises(script_split_engine.TaskPaused) as exc_info:
        asyncio.run(script_split_engine.step_generate_segment(task))

    assert exc_info.value.code == "new_root_location_forbidden"
    assert saved_failures
    assert any(
        error.get("location_id") == "loc_004"
        for error in saved_failures[0][0][2]
    )


def test_disabled_qc_pauses_on_new_root_location_without_forced_accept(monkeypatch):
    parsed = {
        "characters": [],
        "locations": [{
            "location_id": "loc_001",
            "location_name": "模型擅自创建的顶层场景",
            "location_db_id": None,
            "parent_id": None,
        }],
        "props": [],
        "spatial_world": {"space_units": []},
        "shot_groups": [],
    }
    segment = ScriptSplitSegment(
        task_id=101,
        segment_index=1,
        segment_id="seg_0001",
        source_content="短剧本",
    )
    task = ScriptSplitTask(
        id=101,
        request_config={"enable_qc": False},
        accepted_registry_json={},
        continuity_state_json={},
        total_segment_count=1,
    )
    saved_failures = []
    saved_successes = []

    async def fake_parse(**_kwargs):
        return parsed

    monkeypatch.setattr(script_parser, "parse_script_to_shots", fake_parse)
    _prepare_segment_generation_test(monkeypatch, task, segment)
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_failure",
        lambda *args, **kwargs: saved_failures.append((args, kwargs)),
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_success",
        lambda *args, **kwargs: saved_successes.append((args, kwargs)),
    )

    with pytest.raises(script_split_engine.TaskPaused) as exc_info:
        asyncio.run(script_split_engine.step_generate_segment(task))

    assert exc_info.value.code == "new_root_location_forbidden"
    assert saved_successes == []
    assert saved_failures[0][1]["parsed_result"] is parsed
    assert saved_failures[0][0][2][0]["_hard_gate"] is True


def test_exhausted_qc_checkpoint_cannot_force_accept_hard_location_error(monkeypatch):
    parsed = {
        "characters": [],
        "locations": [{
            "location_id": "loc_001",
            "location_name": "非法顶层场景",
            "location_db_id": None,
            "parent_id": None,
        }],
        "props": [],
        "spatial_world": {"space_units": []},
        "shot_groups": [],
    }
    segment = ScriptSplitSegment(
        task_id=102,
        segment_index=1,
        segment_id="seg_0001",
        source_content="短剧本",
        attempt_count=2,
        parsed_result_json=parsed,
        validation_errors=[{
            "code": "new_root_location_forbidden",
            "severity": "error",
            "message": "禁止新建顶层场景",
            "_hard_gate": True,
            "_qc_round": 2,
            "_call_failure_count": 0,
        }],
    )
    task = ScriptSplitTask(
        id=102,
        request_config={"enable_qc": True, "qc_max_rounds": 2},
        accepted_registry_json={},
        continuity_state_json={},
        total_segment_count=1,
    )
    saved_successes = []

    async def forbidden_parse(**_kwargs):
        raise AssertionError("硬门禁轮次耗尽时不应继续调用 LLM")

    monkeypatch.setattr(script_parser, "parse_script_to_shots", forbidden_parse)
    _prepare_segment_generation_test(monkeypatch, task, segment)
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "save_success",
        lambda *args, **kwargs: saved_successes.append((args, kwargs)),
    )

    with pytest.raises(script_split_engine.TaskPaused) as exc_info:
        asyncio.run(script_split_engine.step_generate_segment(task))

    assert exc_info.value.code == "new_root_location_forbidden"
    assert saved_successes == []


def test_reopened_full_graph_error_is_not_cleared_by_segment_only_validation(monkeypatch):
    parsed = {
        "characters": [],
        "locations": [{
            "id": "loc_child",
            "name": "孤儿子场景",
            "location_db_id": None,
            "parent_id": "loc_missing",
        }],
        "props": [],
        "spatial_world": {"space_units": []},
        "shot_groups": [],
    }
    segment = ScriptSplitSegment(
        task_id=103,
        segment_index=1,
        segment_id="seg_0001",
        source_content="短剧本",
        attempt_count=2,
        parsed_result_json=parsed,
        validation_errors=[{
            "code": "location_parent_invalid",
            "severity": "error",
            "message": "父级不存在",
            "_hard_gate": True,
            "_qc_round": 2,
            "_call_failure_count": 0,
        }],
    )
    task = ScriptSplitTask(
        id=103,
        request_config={"enable_qc": True, "qc_max_rounds": 2},
        accepted_registry_json={},
        continuity_state_json={},
        total_segment_count=1,
    )
    _prepare_segment_generation_test(monkeypatch, task, segment)
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_all",
        lambda _task_id: [segment],
    )

    with pytest.raises(script_split_engine.TaskPaused) as exc_info:
        asyncio.run(script_split_engine.step_generate_segment(task))

    assert exc_info.value.code == "location_parent_invalid"


def test_explicitly_reset_qc_round_does_not_fall_back_to_attempt_count(monkeypatch):
    parsed = {
        "characters": [], "locations": [], "props": [],
        "spatial_world": {"space_units": []}, "shot_groups": [],
    }
    parse_calls = []
    segment = ScriptSplitSegment(
        task_id=12,
        segment_index=1,
        segment_id="seg_0001",
        source_block_ids=["block_0001"],
        source_content="短剧本",
        attempt_count=2,
        parsed_result_json=parsed,
        validation_errors=[{
            "code": "QC_REJECTED",
            "severity": "error",
            "message": "上一周期未通过",
            "_qc_round": 0,
            "_call_failure_count": 0,
        }],
    )
    task = ScriptSplitTask(
        id=12,
        request_config={"enable_qc": True, "qc_max_rounds": 2},
        accepted_registry_json={},
        continuity_state_json={},
        total_segment_count=1,
        completed_segment_count=0,
    )

    async def fake_parse(**kwargs):
        parse_calls.append(kwargs)
        return parsed

    monkeypatch.setattr(script_parser, "parse_script_to_shots", fake_parse)
    monkeypatch.setattr(script_split_engine, "_validate_segment", lambda *_args: (True, []))
    async def passing_agent(**_kwargs):
        return QcReport(passed=True)

    monkeypatch.setattr(script_split_engine, "run_script_split_qc", passing_agent)
    _prepare_segment_generation_test(monkeypatch, task, segment)

    asyncio.run(script_split_engine.step_generate_segment(task))

    assert len(parse_calls) == 1
    assert parse_calls[0]["previous_parsed_result"] == parsed
    assert parse_calls[0]["qc_feedback"]["issues"][0]["code"] == "QC_REJECTED"


def test_qc_agent_exception_is_returned_as_validation_error(monkeypatch):
    async def broken_agent(**_kwargs):
        raise RuntimeError("agent unavailable")

    monkeypatch.setattr(script_split_engine, "_validate_segment", lambda *_args: (True, []))
    monkeypatch.setattr(script_split_engine, "run_script_split_qc", broken_agent)
    segment = ScriptSplitSegment(source_content="短剧本")
    task = ScriptSplitTask(id=11, request_config={}, auth_token="token")

    errors = asyncio.run(script_split_engine._run_enabled_segment_qc(
        parsed={"shot_groups": []},
        registry=script_split_engine.AcceptedRegistry(),
        segment=segment,
        config={},
        task=task,
    ))

    assert errors == [{
        "code": "qc_agent_failed",
        "severity": "error",
        "message": "agent unavailable",
    }]


def test_enabled_qc_passes_registry_characters_to_agent(monkeypatch):
    captured = {}

    async def passing_agent(**kwargs):
        captured.update(kwargs)
        return QcReport(passed=True)

    registry = script_split_engine.AcceptedRegistry()
    registry.commit_entity(
        "character",
        "char_001",
        {"id": "char_001", "name": "林诚"},
    )
    monkeypatch.setattr(script_split_engine, "_validate_segment", lambda *_args: (True, []))
    monkeypatch.setattr(script_split_engine, "run_script_split_qc", passing_agent)

    errors = asyncio.run(script_split_engine._run_enabled_segment_qc(
        parsed={"shot_groups": []},
        registry=registry,
        segment=ScriptSplitSegment(source_content="短剧本"),
        config={},
        task=ScriptSplitTask(id=13, request_config={}),
    ))

    assert errors == []
    assert captured["known_characters"] == [{"id": "char_001", "name": "林诚"}]
    assert captured["log_context"].task_id == 13
    assert captured["log_context"].segment_id == ""
    assert captured["log_context"].segment_index is None
    assert captured["log_context"].qc_round == 1


def test_qc_feedback_preserves_issue_location_and_severity():
    segment = ScriptSplitSegment(segment_index=1, segment_id="seg_0001")

    feedback = script_split_engine._build_qc_feedback([{
        "code": "CHAR_NOT_IN_FRAME",
        "severity": "warning",
        "shot_ref": "grp_001/shot_2",
        "field": "opening_frame_description",
        "message": "角色未点名",
    }], segment)

    assert feedback["issues"] == [{
        "code": "CHAR_NOT_IN_FRAME",
        "severity": "warning",
        "shot_ref": "grp_001/shot_2",
        "field": "opening_frame_description",
        "message": "角色未点名",
    }]


def test_segment_exhaustion_pauses_without_replanning():
    task = _planning_task(plan_revision=0)
    segment = ScriptSplitSegment(
        task_id=task.id,
        segment_index=1,
        source_block_ids=["block_0001", "block_0002"],
    )

    with pytest.raises(script_split_engine.TaskPaused) as exc_info:
        script_split_engine._handle_segment_exhausted(
            task, segment, script_split_engine.AcceptedRegistry()
        )

    assert exc_info.value.code == "segment_max_retries"


def test_step_merge_rejects_incomplete_checkpoint_state(monkeypatch):
    task = ScriptSplitTask(id=12, total_segment_count=2)
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_completed",
        lambda _task_id: [],
    )

    with pytest.raises(script_split_engine.EngineError) as exc_info:
        asyncio.run(script_split_engine.step_merge(task))

    assert exc_info.value.code == "invalid_segment_checkpoint_state"


def test_step_merge_preserves_existing_database_location_references(monkeypatch):
    """合并阶段必须用当前世界的场景树核实 DB id，不能把真实场景当成伪造 ID 删除。"""
    task = ScriptSplitTask(
        id=13,
        total_segment_count=1,
        request_config={
            "sequence_mode": "speed",
            "world_id": 6,
            "max_group_duration": 15,
        },
    )
    segment = ScriptSplitSegment(
        task_id=13,
        segment_index=1,
        segment_id="seg_0001",
        parsed_result_json={
            "locations": [
                {
                    "id": "loc_001",
                    "name": "城南酒店大堂",
                    "location_db_id": 565,
                }
            ],
            "shot_groups": [
                {
                    "group_id": "grp_001",
                    "shots": [
                        {
                            "shot_id": "s001",
                            "duration": 5,
                            "location_id": "loc_001",
                        }
                    ],
                }
            ],
        },
    )
    saved = {}
    location_queries = []

    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_completed",
        lambda _task_id: [segment],
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "save_field",
        lambda _task_id, **kwargs: saved.update(kwargs),
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "update_status",
        lambda *args, **kwargs: None,
    )

    from model.location import LocationModel

    def fake_get_tree_by_world(world_id, limit=None):
        location_queries.append((world_id, limit))
        return [{"id": 565, "name": "城南酒店大堂", "children": []}]

    monkeypatch.setattr(LocationModel, "get_tree_by_world", fake_get_tree_by_world)
    monkeypatch.setattr(
        script_parser, "sanitize_parsed_prop_references", lambda parsed: parsed
    )
    monkeypatch.setattr(
        script_parser, "repair_spatial_layout_continuity", lambda parsed: parsed
    )
    monkeypatch.setattr(
        script_parser, "reorganize_shot_groups", lambda parsed, _duration: parsed
    )
    monkeypatch.setattr(script_split_engine, "renumber_global", lambda parsed: parsed)

    asyncio.run(script_split_engine.step_merge(task))

    final_result = saved["final_result_json"]
    assert location_queries == [(6, None)]
    assert final_result["locations"][0]["location_db_id"] == 565
    assert final_result["shot_groups"][0]["shots"][0]["location_id"] == "loc_001"


def test_step_merge_converts_quality_strategy_error_to_engine_error(monkeypatch):
    task = ScriptSplitTask(
        id=14,
        total_segment_count=1,
        request_config={"sequence_mode": "quality"},
        segment_plan_json={"schema_version": 2},
    )
    segment = ScriptSplitSegment(
        task_id=14,
        segment_index=1,
        segment_id="seg_0001",
        parsed_result_json={"shot_groups": []},
    )

    class BrokenQualityStrategy:
        parallel_enabled = True

        def repair_merged_result(self, _merged, _plan):
            raise ValueError("entity id conflict: loc_001")

    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_completed",
        lambda _task_id: [segment],
    )
    monkeypatch.setattr(
        script_split_engine,
        "get_script_split_strategy",
        lambda _mode: BrokenQualityStrategy(),
    )
    monkeypatch.setattr(
        script_parser,
        "sanitize_parsed_prop_references",
        lambda parsed: parsed,
    )
    monkeypatch.setattr(
        script_parser,
        "sanitize_parsed_location_references",
        lambda parsed: parsed,
    )

    with pytest.raises(script_split_engine.EngineError) as exc_info:
        asyncio.run(script_split_engine.step_merge(task))

    assert exc_info.value.code == "quality_merge_invalid"
    assert "loc_001" in exc_info.value.message


def test_step_merge_reopens_completed_segment_when_location_graph_is_illegal(monkeypatch):
    task = ScriptSplitTask(
        id=15,
        total_segment_count=1,
        request_config={"sequence_mode": "speed"},
    )
    segment = ScriptSplitSegment(
        task_id=15,
        segment_index=1,
        segment_id="seg_0001",
        status="completed",
        parsed_result_json={
            "locations": [{
                "id": "loc_001",
                "name": "非法新顶层",
                "location_db_id": None,
                "parent_id": None,
            }],
            "shot_groups": [],
        },
    )
    reopened = []
    saved = []

    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "get_completed",
        lambda _task_id: [segment],
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitSegmentModel,
        "reopen_completed_for_hard_errors",
        lambda task_id, errors_by_segment: reopened.append((task_id, errors_by_segment)) or 0,
        raising=False,
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "save_field",
        lambda _task_id, **kwargs: saved.append(kwargs),
    )
    monkeypatch.setattr(
        script_split_engine.ScriptSplitTaskModel,
        "update_status",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(script_parser, "sanitize_parsed_prop_references", lambda parsed: parsed)
    monkeypatch.setattr(
        script_parser,
        "sanitize_parsed_location_references",
        lambda parsed, _db_locations=None: parsed,
    )
    monkeypatch.setattr(script_parser, "repair_spatial_layout_continuity", lambda parsed: parsed)
    monkeypatch.setattr(script_parser, "reorganize_shot_groups", lambda parsed, _duration: parsed)
    monkeypatch.setattr(script_split_engine, "renumber_global", lambda parsed: parsed)

    with pytest.raises(script_split_engine.TaskPaused) as exc_info:
        asyncio.run(script_split_engine.step_merge(task))

    assert exc_info.value.code == "new_root_location_forbidden"
    assert reopened[0][0] == 15
    assert reopened[0][1][1][0]["location_id"] == "loc_001"
    assert not any("final_result_json" in fields for fields in saved)
