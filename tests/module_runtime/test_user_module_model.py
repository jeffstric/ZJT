import importlib.util
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]  # 主仓根（ABI/alembic 留在主仓）
# model 实体已随用户模块子系统常驻主仓 model/；其 DB 访问是绝对导入
# `from model.database import ...`，这里用假 model 包拦截，避免测试环境连库。
_INJECTED = {}
_fake_model = types.ModuleType("model")
_fake_model.__path__ = []
_fake_database = types.ModuleType("model.database")
_fake_database.execute_query = lambda *args, **kwargs: None
_fake_database.execute_update = lambda *args, **kwargs: 0
_fake_database.transaction = lambda: None
for _name, _mod in (
    ("model", _fake_model),
    ("model.database", _fake_database),
):
    if _name not in sys.modules:
        sys.modules[_name] = _mod
        _INJECTED[_name] = _mod
spec = importlib.util.spec_from_file_location(
    "_user_modules_under_test",
    PROJECT_ROOT / "model" / "user_modules.py",
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)
for _name in _INJECTED:
    sys.modules.pop(_name, None)

CREATE_TABLE_SQL = module.CREATE_TABLE_SQL
ModuleJobEntity = module.ModuleJobEntity
ModuleJobStatus = module.ModuleJobStatus
UserModuleReleaseEntity = module.UserModuleReleaseEntity
UserModuleEntity = module.UserModuleEntity


def test_release_entity_decodes_manifest_json():
    entity = UserModuleReleaseEntity.from_row(
        {
            "id": 7,
            "module_id": "demo.echo",
            "version": "1.0.0",
            "code_digest": "sha256:" + "a" * 64,
            "rpc_protocol": "user-module-rpc/v1",
            "driver_protocol": "media-driver/v1",
            "sdk_version": "1.0.0",
            "manifest_json": '{"module_id":"demo.echo"}',
            "release_path": "modules/demo.echo/releases/1.0.0-a",
            "status": "ready",
            "compatibility_status": "compatible",
        }
    )
    assert entity.manifest["module_id"] == "demo.echo"


def test_module_entity_decodes_admin_list_summary():
    entity = UserModuleEntity.from_row(
        {
            "id": 3,
            "module_id": "demo.echo",
            "name": "Echo",
            "enabled": 1,
            "active_release_id": 7,
            "status": "active",
            "active_version": "1.2.0",
            "active_code_digest": "sha256:" + "a" * 64,
            "active_release_status": "active",
            "active_manifest_json": '{"capabilities":[{"operation":"generate"}]}',
            "release_count": 2,
        }
    )

    assert entity.enabled is True
    assert entity.active_version == "1.2.0"
    assert entity.release_count == 2
    assert entity.active_manifest["capabilities"][0]["operation"] == "generate"


def test_job_entity_keeps_pinned_release_identity():
    entity = ModuleJobEntity.from_row(
        {
            "job_id": "job-1",
            "release_id": 7,
            "module_id": "demo.echo",
            "module_version": "1.0.0",
            "code_digest": "sha256:" + "a" * 64,
            "protocol_version": "media-driver/v1",
            "requester_id": "user-1",
            "operation": "echo_image",
            "media_kind": "image",
            "status": ModuleJobStatus.QUEUED,
            "idempotency_key": "idem-key",
            "completion_modes": '["immediate"]',
            "request_json": '{"prompt":"hello"}',
        }
    )
    assert entity.release_id == 7
    assert entity.module_version == "1.0.0"
    assert entity.completion_modes == ["immediate"]


def test_create_table_sql_contains_release_pin_and_gc_indexes():
    assert "CREATE TABLE IF NOT EXISTS `user_module`" in CREATE_TABLE_SQL
    assert "CREATE TABLE IF NOT EXISTS `user_module_release`" in CREATE_TABLE_SQL
    assert "CREATE TABLE IF NOT EXISTS `module_job`" in CREATE_TABLE_SQL
    assert "`release_id` BIGINT NOT NULL" in CREATE_TABLE_SQL
    assert "`code_digest` VARCHAR(80) NOT NULL" in CREATE_TABLE_SQL
    assert "idx_module_job_release_status" in CREATE_TABLE_SQL


def test_migration_is_chained_to_current_head():
    migration = (
        Path(__file__).resolve().parents[2]  # 主仓根（ABI/alembic 留在主仓）
        / "alembic"
        / "versions"
        / "20260811_create_user_modules.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "20260811_user_modules"' in migration
    assert 'down_revision: Union[str, None] = "20260810_add_agnes"' in migration
    assert '"module_job"' in migration
    assert migration.count("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP") == 3
