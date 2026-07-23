import asyncio
import json
from types import SimpleNamespace

from config.constant import ScriptSplitConstants
from llm import script_segment_planner as planner


ANCHORS = [
    {
        "block_id": "block_0001",
        "start_line": 1,
        "end_line": 1,
        "summary": "室内开场",
        "content": "INT. ROOM - DAY",
    }
]


def _response(content, finish_reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content),
            )
        ]
    )


def _install_client(monkeypatch, result):
    class FakeClient:
        def call_api(self, **_kwargs):
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(planner, "get_llm_client", lambda *_args, **_kwargs: FakeClient())


def _plan_json():
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


def _run_plan(context, auth_token="secret-token"):
    return asyncio.run(
        planner.plan_segments(
            anchors=ANCHORS,
            model="test-model",
            auth_token=auth_token,
            vendor_id=None,
            model_id=None,
            log_context=context,
        )
    )


def test_plan_segments_writes_correlated_diagnostic_files(monkeypatch, tmp_path):
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOGGING_ENABLED", True)
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOG_DIR", str(tmp_path))
    plan_data = _plan_json()
    _install_client(monkeypatch, _response(json.dumps(plan_data, ensure_ascii=False)))

    context = planner.create_plan_log_context(42, "initial", 1)
    plan, finish_reason = _run_plan(context)

    assert plan == plan_data
    assert finish_reason == "stop"
    paths = {path.name.removeprefix(f"{context.prefix}_"): path for path in tmp_path.iterdir()}
    assert set(paths) == {
        "01_anchors.json",
        "02_prompt.txt",
        "03_raw_response.txt",
        "04_parsed_plan.json",
    }
    assert json.loads(paths["01_anchors.json"].read_text(encoding="utf-8")) == ANCHORS
    assert json.loads(paths["04_parsed_plan.json"].read_text(encoding="utf-8")) == plan_data
    assert "secret-token" not in "".join(
        path.read_text(encoding="utf-8") for path in paths.values()
    )


def test_invalid_json_keeps_raw_response_without_parsed_plan(monkeypatch, tmp_path):
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOGGING_ENABLED", True)
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOG_DIR", str(tmp_path))
    _install_client(monkeypatch, _response("```json\nnot valid json\n```"))
    context = planner.create_plan_log_context(43, "initial", 1)

    plan, _ = _run_plan(context, auth_token=None)

    assert plan == {}
    assert context.parse_error
    assert next(tmp_path.glob("*_03_raw_response.txt")).read_text(encoding="utf-8") == (
        "```json\nnot valid json\n```"
    )
    assert not list(tmp_path.glob("*_04_parsed_plan.json"))


def test_call_failure_writes_empty_raw_response_and_reraises(monkeypatch, tmp_path):
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOGGING_ENABLED", True)
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOG_DIR", str(tmp_path))
    _install_client(monkeypatch, RuntimeError("provider unavailable"))
    context = planner.create_plan_log_context(44, "initial", 1)

    try:
        _run_plan(context, auth_token=None)
    except RuntimeError as exc:
        assert str(exc) == "provider unavailable"
    else:
        raise AssertionError("expected provider failure")

    assert next(tmp_path.glob("*_03_raw_response.txt")).read_text(encoding="utf-8") == ""
    assert not list(tmp_path.glob("*_04_parsed_plan.json"))


def test_logging_disabled_creates_no_context_or_files(monkeypatch, tmp_path):
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOGGING_ENABLED", False)
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOG_DIR", str(tmp_path))
    _install_client(monkeypatch, _response(json.dumps(_plan_json())))

    context = planner.create_plan_log_context(45, "initial", 1)
    _run_plan(context, auth_token=None)

    assert context is None
    assert list(tmp_path.iterdir()) == []


def test_log_context_uses_microseconds_to_avoid_overwrite(monkeypatch):
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOGGING_ENABLED", True)

    first = planner.create_plan_log_context(46, "initial", 1)
    second = planner.create_plan_log_context(46, "initial", 1)

    assert first.prefix != second.prefix
    assert first.timestamp.count("_") == 2
    assert len(first.timestamp.rsplit("_", 1)[1]) == 6


def test_diagnostic_file_writes_use_asyncio_to_thread(monkeypatch, tmp_path):
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOGGING_ENABLED", True)
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOG_DIR", str(tmp_path))
    _install_client(monkeypatch, _response(json.dumps(_plan_json())))
    original_to_thread = asyncio.to_thread
    calls = []

    async def tracking_to_thread(func, /, *args, **kwargs):
        calls.append(func.__name__)
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", tracking_to_thread)
    context = planner.create_plan_log_context(47, "initial", 1)

    _run_plan(context, auth_token=None)

    assert calls.count("_write_text_file") == 4
    assert "call_api" in calls


def test_validation_log_uses_same_context_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOGGING_ENABLED", True)
    monkeypatch.setattr(ScriptSplitConstants, "PLANNER_DIAGNOSTIC_LOG_DIR", str(tmp_path))
    context = planner.create_plan_log_context(48, "initial", 2)
    payload = {
        "task_id": 48,
        "plan_kind": "initial",
        "attempt": 2,
        "passed": False,
        "finish_reason": "stop",
        "segment_count": 0,
        "errors": [{"code": "segment_gap", "message": "未覆盖全部 block"}],
        "segments": [],
    }

    asyncio.run(planner.write_plan_validation_log(context, payload))

    path = tmp_path / f"{context.prefix}_05_validation.json"
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_plan_segments_uses_enterprise_prompt_override(monkeypatch):
    captured = {}

    class FakeClient:
        def call_api(self, **kwargs):
            captured.update(kwargs)
            return _response(json.dumps(_plan_json(), ensure_ascii=False))

    monkeypatch.setattr(
        planner,
        "get_llm_client",
        lambda *_args, **_kwargs: FakeClient(),
    )

    asyncio.run(
        planner.plan_segments(
            anchors=ANCHORS,
            model="test-model",
            auth_token=None,
            vendor_id=None,
            model_id=None,
            prompt_override="QUALITY SCHEMA VERSION 2",
        )
    )

    assert captured["messages"][0]["content"] == "QUALITY SCHEMA VERSION 2"
