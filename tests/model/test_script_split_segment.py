import json

import pytest

from model import script_split_segment
from model.script_split_segment import ScriptSplitSegment, ScriptSplitSegmentModel


def test_replace_all_rejects_empty_segments_before_database_access():
    with pytest.raises(ValueError, match="segments must not be empty"):
        ScriptSplitSegmentModel.replace_all(2, [])


def test_save_failure_can_checkpoint_latest_complete_candidate(monkeypatch):
    calls = []
    monkeypatch.setattr(
        script_split_segment,
        "execute_update",
        lambda sql, params: calls.append((sql, params)),
    )
    parsed = {"characters": [], "shot_groups": [{"shots": []}]}

    ScriptSplitSegmentModel.save_failure(
        7,
        1,
        [{"code": "QC_REJECTED", "message": "需要修复"}],
        parsed_result=parsed,
    )

    sql, params = calls[0]
    assert "parsed_result_json = %s" in sql
    assert json.dumps(parsed, ensure_ascii=False) in params


def test_save_success_can_preserve_forced_accept_errors(monkeypatch):
    calls = []
    monkeypatch.setattr(
        script_split_segment,
        "execute_update",
        lambda sql, params: calls.append((sql, params)),
    )
    errors = [{
        "code": "QC_REJECTED",
        "message": "达到质检上限后采用最后候选",
        "_forced_accept": True,
    }]

    ScriptSplitSegmentModel.save_success(
        7,
        1,
        {"shot_groups": []},
        {},
        validation_errors=errors,
    )

    sql, params = calls[0]
    assert "validation_errors = %s" in sql
    assert json.dumps(errors, ensure_ascii=False) in params


def test_reset_retry_budget_preserves_feedback_and_resets_internal_counters(monkeypatch):
    calls = []
    segment = ScriptSplitSegment(
        task_id=15,
        segment_index=1,
        status="generating",
        attempt_count=2,
        validation_errors=[{
            "code": "TOO_MANY_EMPTY_DIALOGUE_SHOTS",
            "message": "旧规则错误",
            "_qc_round": 2,
            "_call_failure_count": 1,
        }],
        parsed_result_json={"shot_groups": []},
    )
    monkeypatch.setattr(
        ScriptSplitSegmentModel,
        "get_first_uncompleted",
        lambda _task_id: segment,
    )
    monkeypatch.setattr(
        script_split_segment,
        "execute_update",
        lambda sql, params: calls.append((sql, params)),
    )

    ScriptSplitSegmentModel.reset_retry_budget(15)

    sql, params = calls[0]
    assert "status = %s" in sql
    assert "validation_errors = %s" in sql
    assert "attempt_count" not in sql
    assert params[0] == "failed"
    reset_errors = json.loads(params[1])
    assert reset_errors[0]["code"] == "TOO_MANY_EMPTY_DIALOGUE_SHOTS"
    assert reset_errors[0]["_qc_round"] == 0
    assert reset_errors[0]["_call_failure_count"] == 0


@pytest.mark.parametrize("method_name", ["get_all", "get_completed"])
def test_segment_list_queries_explicitly_fetch_all_rows(monkeypatch, method_name):
    calls = []
    row = {
        "task_id": 15,
        "segment_index": 1,
        "segment_id": "seg_0001",
        "status": "completed",
    }

    def fake_execute_query(sql, params=None, fetch_one=False, fetch_all=False):
        calls.append({
            "sql": sql,
            "params": params,
            "fetch_one": fetch_one,
            "fetch_all": fetch_all,
        })
        return [row] if fetch_all else None

    monkeypatch.setattr(script_split_segment, "execute_query", fake_execute_query)

    segments = getattr(ScriptSplitSegmentModel, method_name)(15)

    assert calls[0]["fetch_all"] is True
    assert len(segments) == 1
    assert segments[0].segment_id == "seg_0001"


def test_get_uncompleted_uses_bounded_ordered_batch(monkeypatch):
    calls = []

    def fake_execute_query(sql, params=None, fetch_one=False, fetch_all=False):
        calls.append((sql, params, fetch_one, fetch_all))
        return [{
            "task_id": 15,
            "segment_index": 2,
            "segment_id": "seg_0002",
            "status": "pending",
        }]

    monkeypatch.setattr(script_split_segment, "execute_query", fake_execute_query)

    segments = ScriptSplitSegmentModel.get_uncompleted(15, 3)

    assert "ORDER BY segment_index ASC LIMIT 3" in calls[0][0]
    assert calls[0][3] is True
    assert segments[0].segment_id == "seg_0002"
