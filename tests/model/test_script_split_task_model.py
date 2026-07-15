from model import script_split_task
from model.script_split_task import ScriptSplitTaskModel


def test_update_status_can_clear_previous_error(monkeypatch):
    calls = []
    monkeypatch.setattr(
        script_split_task,
        "execute_update",
        lambda sql, params: calls.append((sql, params)),
    )

    ScriptSplitTaskModel.update_status(
        15,
        "generating",
        phase="segment_generation",
        clear_error=True,
    )

    sql, params = calls[0]
    assert "last_error_code = NULL" in sql
    assert "last_error_message = NULL" in sql
    assert params == ("generating", "segment_generation", 15)
