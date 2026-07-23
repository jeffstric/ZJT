"""剧本分段拆分迁移的 SQL 回归测试。"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    PROJECT_ROOT / "alembic" / "versions" / "no_115_20260714_script_split_tasks.py"
)


def _load_migration_module():
    spec = spec_from_file_location("script_split_migration", MIGRATION_PATH)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, *args, **kwargs):
        self.statements.append(str(statement))


def test_script_split_task_id_comment_closes_before_after_clause(monkeypatch):
    migration = _load_migration_module()
    connection = _RecordingConnection()

    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    monkeypatch.setattr(migration, "_table_exists", lambda *args: True)
    monkeypatch.setattr(
        migration,
        "_column_exists",
        lambda _conn, _table, column: column != "script_split_task_id",
    )
    monkeypatch.setattr(migration, "_index_exists", lambda *args: True)

    migration.upgrade()

    statement = next(
        sql for sql in connection.statements if "`script_split_task_id`" in sql
    )
    assert (
        "COMMENT '剧本分段拆分任务 id（发布幂等，NULL=非拆分来源）' "
        "AFTER `last_modified_user_id`"
    ) in statement


def test_source_shot_key_comment_closes_before_after_clause(monkeypatch):
    migration = _load_migration_module()
    connection = _RecordingConnection()

    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    monkeypatch.setattr(migration, "_table_exists", lambda *args: True)
    monkeypatch.setattr(
        migration,
        "_column_exists",
        lambda _conn, _table, column: column != "source_shot_key",
    )
    monkeypatch.setattr(migration, "_index_exists", lambda *args: True)

    migration.upgrade()

    statement = next(
        sql for sql in connection.statements if "`source_shot_key`" in sql
    )
    assert (
        "COMMENT '拆分任务内稳定 shot 标识（发布幂等去重）' "
        "AFTER `script_split_task_id`"
    ) in statement
