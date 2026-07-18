from contextlib import contextmanager

from model import script_split_task
from model.script_split_task import ScriptSplitTask, ScriptSplitTaskModel


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


def test_claim_applies_lease_filter_to_queued_and_generates_unique_owner(monkeypatch):
    statements = []
    owners = []

    class Cursor:
        def execute(self, sql, params):
            statements.append((sql, params))
            if sql.lstrip().startswith("UPDATE script_split_task"):
                owners.append(params[0])

        def fetchall(self):
            return [(41,)]

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def fake_transaction():
        yield Connection()

    monkeypatch.setattr(script_split_task, "transaction", fake_transaction)
    monkeypatch.setattr(
        ScriptSplitTaskModel,
        "get_by_id",
        staticmethod(lambda task_id: ScriptSplitTask(id=task_id, worker_id=owners[-1])),
    )

    first = ScriptSplitTaskModel.claim_next_task(720)
    second = ScriptSplitTaskModel.claim_next_task(720)

    select_sql = next(sql for sql, _ in statements if "SELECT id" in sql)
    normalized = " ".join(select_sql.split())
    assert "status IN" in normalized
    assert "status = %s OR" not in normalized
    assert "AND (lease_until IS NULL OR lease_until < NOW())" in normalized
    assert first.worker_id != second.worker_id
    assert len(first.worker_id) <= 64


def test_renew_and_release_are_fenced_by_claim_owner(monkeypatch):
    calls = []
    results = iter([1, 0])
    monkeypatch.setattr(
        script_split_task,
        "execute_update",
        lambda sql, params: (calls.append((sql, params)), next(results))[1],
    )

    assert ScriptSplitTaskModel.renew_lease(15, "owner-a", 720) is True
    assert ScriptSplitTaskModel.release_lease(15, "owner-a") is False

    assert all("worker_id = %s" in sql for sql, _ in calls)
    assert calls[0][1] == (720, 15, "owner-a")
    assert calls[1][1] == (15, "owner-a")
