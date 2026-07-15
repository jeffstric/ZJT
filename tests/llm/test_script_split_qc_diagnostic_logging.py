import asyncio
import json

from config.constant import ScriptSplitQcConstants
from llm import script_split_qc_agent as qc_agent


def _parsed_data():
    return {
        "characters": [{"id": "char_001", "name": "林诚"}],
        "locations": [],
        "props": [],
        "spatial_world": {"space_units": []},
        "shot_groups": [{
            "group_id": "grp_001",
            "shots": [{
                "shot_number": 1,
                "duration": 2,
                "characters_present": ["char_001"],
                "opening_frame_description": "近景：【【林诚】】坐在桌前。",
            }],
        }],
    }


def _run_qc(context, auth_token="secret-token-must-not-be-logged"):
    return asyncio.run(qc_agent.run_script_split_qc(
        parsed_data=_parsed_data(),
        script_content="林诚坐在桌前。",
        known_characters=[{"id": "char_001", "name": "林诚"}],
        auth_token=auth_token,
        use_llm=False,
        log_context=context,
    ))


def test_rule_qc_writes_correlated_input_prompt_status_and_report(monkeypatch, tmp_path):
    monkeypatch.setattr(ScriptSplitQcConstants, "DIAGNOSTIC_LOG_DIR", str(tmp_path))
    context = qc_agent.create_qc_log_context(
        task_id=42,
        segment_id="seg_0001",
        segment_index=1,
        qc_round=2,
    )

    report = _run_qc(context)

    assert report.passed
    paths = {path.name.removeprefix(f"{context.prefix}_"): path for path in tmp_path.iterdir()}
    assert set(paths) == {
        "01_system_prompt.txt",
        "02_input.json",
        "03_report.json",
    }
    system_prompt = paths["01_system_prompt.txt"].read_text(encoding="utf-8")
    assert "rule_only" in system_prompt
    assert "未调用 LLM" in system_prompt

    input_data = json.loads(paths["02_input.json"].read_text(encoding="utf-8"))
    assert input_data["execution_mode"] == "rule_only"
    assert input_data["task_id"] == 42
    assert input_data["segment_id"] == "seg_0001"
    assert input_data["qc_round"] == 2
    assert input_data["parsed_data"] == _parsed_data()
    assert input_data["known_characters"] == [{"id": "char_001", "name": "林诚"}]

    report_data = json.loads(paths["03_report.json"].read_text(encoding="utf-8"))
    assert report_data["passed"] is True
    all_text = "".join(path.read_text(encoding="utf-8") for path in paths.values())
    assert "secret-token-must-not-be-logged" not in all_text


def test_qc_diagnostic_logging_disabled_creates_no_context_or_files(monkeypatch, tmp_path):
    monkeypatch.setattr(ScriptSplitQcConstants, "DIAGNOSTIC_LOGGING_ENABLED", False)
    monkeypatch.setattr(ScriptSplitQcConstants, "DIAGNOSTIC_LOG_DIR", str(tmp_path))

    context = qc_agent.create_qc_log_context(43, "seg_0001", 1, 1)
    _run_qc(context, auth_token=None)

    assert context is None
    assert list(tmp_path.iterdir()) == []


def test_qc_diagnostic_file_writes_use_asyncio_to_thread(monkeypatch, tmp_path):
    monkeypatch.setattr(ScriptSplitQcConstants, "DIAGNOSTIC_LOG_DIR", str(tmp_path))
    original_to_thread = asyncio.to_thread
    calls = []

    async def tracking_to_thread(func, /, *args, **kwargs):
        calls.append(func.__name__)
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", tracking_to_thread)
    context = qc_agent.create_qc_log_context(44, "seg_0002", 2, 1)

    _run_qc(context, auth_token=None)

    assert calls.count("_write_text_file") == 3
