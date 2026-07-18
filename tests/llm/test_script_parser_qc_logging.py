import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm import script_parser
from llm.script_split_qc_agent import QcIssue, QcReport


class _FakeClient:
    def __init__(self, captured_messages):
        self.captured_messages = captured_messages

    def call_api(self, **kwargs):
        self.captured_messages.extend(kwargs["messages"])
        content = json.dumps({
            "characters": [],
            "locations": [],
            "props": [],
            "spatial_world": {"space_units": []},
            "shot_groups": [],
        })
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


def _run_parser(
    monkeypatch,
    tmp_path,
    qc_feedback,
    *,
    logging_enabled=True,
    segment_context=None,
):
    captured_messages = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        script_parser,
        "get_llm_client",
        lambda model, vendor_id=None: _FakeClient(captured_messages),
    )
    monkeypatch.setattr(
        script_parser,
        "ENABLE_SCRIPT_PARSER_LOGGING",
        logging_enabled,
    )

    asyncio.run(script_parser.parse_script_to_shots(
        script_content="INT. ROOM - DAY",
        model="fake-model",
        auth_token="secret-token-must-not-be-logged",
        previous_parsed_result={
            "characters": [],
            "locations": [],
            "props": [],
            "spatial_world": {"space_units": []},
            "shot_groups": [],
        },
        qc_feedback=qc_feedback,
        segment_context=segment_context or {
            "segment_id": "seg_0001", "segment_index": 1, "total_segments": 1,
        },
        strict_json=True,
    ))
    return captured_messages


def test_v3_prompt_requests_incremental_intent_and_compact_state(monkeypatch, tmp_path):
    messages = _run_parser(
        monkeypatch,
        tmp_path,
        None,
        segment_context={
            "segment_id": "seg_0002",
            "segment_index": 2,
            "total_segments": 3,
            "quality_mode": True,
            "spatial_state_version": 1,
            "previous_state": {
                "char_001": ["present", "space:room", "container:sofa", "left"],
            },
            "spatial_catalog_prompt": {
                "space_units": ["space:room"],
                "containers": ["container:sofa"],
                "slots": ["container:sofa/left"],
                "anchors": [],
            },
            "planned_state_changes": [],
            "previous_camera_summary": {"space_unit_id": "space:room"},
        },
    )

    prompt = next(item["content"] for item in messages if item["role"] == "user")
    assert "spatial_intent.state_changes" in prompt
    assert "characters_present 和 props_present 是唯一可见性真源" in prompt
    assert "offscreen_continuity" in prompt
    assert '"char_001": ["present", "space:room", "container:sofa", "left"]' in prompt
    assert "禁止自造 anchor_id" in prompt
    assert "visible_character_ids" not in prompt
    assert "continuity_in" not in prompt
    assert "continuity_out" not in prompt


@pytest.mark.parametrize(
    ("qc_feedback", "expected_log"),
    [
        (
            {"summary": "规则失败", "issues": [{"code": "bad_ref", "severity": "error"}]},
            {"summary": "规则失败", "issues": [{"code": "bad_ref", "severity": "error"}]},
        ),
        (
            QcReport(
                passed=False,
                summary="质检失败",
                issues=[QcIssue(code="bad_ref", severity="error", message="引用不存在")],
            ),
            {
                "passed": False,
                "summary": "质检失败",
                "stats": {},
                "issues": [{
                    "code": "bad_ref",
                    "severity": "error",
                    "message": "引用不存在",
                    "shot_ref": "",
                    "field": "",
                    "evidence": "",
                }],
            },
        ),
        ("纯文本反馈", {"text": "纯文本反馈"}),
    ],
)
def test_qc_retry_writes_feedback_and_injected_prompt_logs(
    monkeypatch, tmp_path, qc_feedback, expected_log
):
    captured_messages = _run_parser(monkeypatch, tmp_path, qc_feedback)
    log_dir = tmp_path / "logs" / "script_parser"
    feedback_files = list(log_dir.glob("*_03_qc_feedback.json"))
    prompt_files = list(log_dir.glob("*_03_qc_retry_prompt.txt"))

    assert len(feedback_files) == 1
    assert len(prompt_files) == 1
    assert json.loads(feedback_files[0].read_text(encoding="utf-8")) == expected_log

    retry_prompt = prompt_files[0].read_text(encoding="utf-8")
    user_prompt = next(message["content"] for message in captured_messages if message["role"] == "user")
    assert retry_prompt in user_prompt
    assert "当前段完整 JSON" in retry_prompt
    for key in ("characters", "locations", "props", "spatial_world", "shot_groups"):
        assert key in retry_prompt
    assert "secret-token-must-not-be-logged" not in retry_prompt
    assert "secret-token-must-not-be-logged" not in feedback_files[0].read_text(encoding="utf-8")


def test_qc_logs_are_not_created_when_logging_is_disabled(monkeypatch, tmp_path):
    _run_parser(monkeypatch, tmp_path, {"summary": "失败"}, logging_enabled=False)

    assert not (tmp_path / "logs" / "script_parser").exists()


def test_qc_logs_are_not_created_without_retry_context(monkeypatch, tmp_path):
    captured_messages = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(script_parser, "ENABLE_SCRIPT_PARSER_LOGGING", True)
    monkeypatch.setattr(
        script_parser,
        "get_llm_client",
        lambda model, vendor_id=None: _FakeClient(captured_messages),
    )

    asyncio.run(script_parser.parse_script_to_shots(
        script_content="INT. ROOM - DAY",
        model="fake-model",
        strict_json=True,
    ))

    log_dir = tmp_path / "logs" / "script_parser"
    assert list(log_dir.glob("*_03_qc_*")) == []


def test_log_directory_creation_runs_off_event_loop(monkeypatch, tmp_path):
    main_thread_id = threading.get_ident()
    mkdir_thread_ids = []
    original_mkdir = Path.mkdir

    def tracking_mkdir(path, *args, **kwargs):
        mkdir_thread_ids.append(threading.get_ident())
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", tracking_mkdir)
    _run_parser(monkeypatch, tmp_path, {"summary": "失败"})

    assert mkdir_thread_ids
    assert all(thread_id != main_thread_id for thread_id in mkdir_thread_ids)
