"""用户模块、不可变 Release 与版本钉住任务的数据访问层。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from model.database import execute_query, execute_update, transaction

logger = logging.getLogger(__name__)


class UserModuleStatus:
    DISABLED = "disabled"
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    # 软删除：list_modules 不展示、绑定自动失效；release 与历史 module_job 记录保留
    DELETED = "deleted"


class UserModuleReleaseStatus:
    STAGED = "staged"
    READY = "ready"
    ACTIVE = "active"
    DRAINING = "draining"
    INCOMPATIBLE = "incompatible"
    FAILED = "failed"


class ModuleJobStatus:
    QUEUED = "queued"
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    PAUSED = "paused"
    INCOMPATIBLE = "incompatible"

    TERMINAL = (SUCCEEDED, FAILED, CANCELLED, TIMED_OUT)


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


@dataclass
class UserModuleEntity:
    id: int
    module_id: str
    name: str
    enabled: bool
    active_release_id: Optional[int]
    status: str
    last_error: Optional[str] = None
    active_version: Optional[str] = None
    active_code_digest: Optional[str] = None
    active_release_status: Optional[str] = None
    active_manifest: Optional[Dict[str, Any]] = None
    release_count: int = 0
    create_at: Any = None
    update_at: Any = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "UserModuleEntity":
        return cls(
            id=row["id"],
            module_id=row["module_id"],
            name=row["name"],
            enabled=bool(row.get("enabled")),
            active_release_id=row.get("active_release_id"),
            status=row["status"],
            last_error=row.get("last_error"),
            active_version=row.get("active_version"),
            active_code_digest=row.get("active_code_digest"),
            active_release_status=row.get("active_release_status"),
            active_manifest=_json_value(row.get("active_manifest_json"), None),
            release_count=int(row.get("release_count") or 0),
            create_at=row.get("create_at"),
            update_at=row.get("update_at"),
        )


@dataclass
class UserModuleReleaseEntity:
    id: int
    module_id: str
    version: str
    code_digest: str
    rpc_protocol: str
    driver_protocol: str
    sdk_version: str
    manifest: Dict[str, Any]
    release_path: str
    status: str
    compatibility_status: str
    last_error: Optional[str] = None
    create_at: Any = None
    update_at: Any = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "UserModuleReleaseEntity":
        return cls(
            id=row["id"],
            module_id=row["module_id"],
            version=row["version"],
            code_digest=row["code_digest"],
            rpc_protocol=row["rpc_protocol"],
            driver_protocol=row["driver_protocol"],
            sdk_version=row["sdk_version"],
            manifest=_json_value(row.get("manifest_json"), {}),
            release_path=row["release_path"],
            status=row["status"],
            compatibility_status=row["compatibility_status"],
            last_error=row.get("last_error"),
            create_at=row.get("create_at"),
            update_at=row.get("update_at"),
        )


@dataclass
class ModuleJobEntity:
    job_id: str
    release_id: int
    module_id: str
    module_version: str
    code_digest: str
    protocol_version: str
    requester_id: str
    operation: str
    media_kind: str
    status: str
    idempotency_key: str
    completion_modes: List[str]
    request: Dict[str, Any]
    external_job_id: Optional[str] = None
    handle: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    progress: Optional[float] = None
    next_poll_at: Any = None
    timeout_at: Any = None
    callback_token_hash: Optional[str] = None
    create_at: Any = None
    update_at: Any = None
    complete_at: Any = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "ModuleJobEntity":
        return cls(
            job_id=row["job_id"],
            release_id=row["release_id"],
            module_id=row["module_id"],
            module_version=row["module_version"],
            code_digest=row["code_digest"],
            protocol_version=row["protocol_version"],
            requester_id=row["requester_id"],
            operation=row["operation"],
            media_kind=row["media_kind"],
            status=row["status"],
            idempotency_key=row["idempotency_key"],
            completion_modes=_json_value(row.get("completion_modes"), []),
            request=_json_value(row.get("request_json"), {}),
            external_job_id=row.get("external_job_id"),
            handle=_json_value(row.get("handle_json"), None),
            result=_json_value(row.get("result_json"), None),
            error=_json_value(row.get("error_json"), None),
            progress=row.get("progress"),
            next_poll_at=row.get("next_poll_at"),
            timeout_at=row.get("timeout_at"),
            callback_token_hash=row.get("callback_token_hash"),
            create_at=row.get("create_at"),
            update_at=row.get("update_at"),
            complete_at=row.get("complete_at"),
        )


class UserModulesModel:
    @staticmethod
    def register_release(manifest: Dict[str, Any], release_path: str) -> int:
        """幂等登记模块和不可变 Release，返回 release id。"""

        module_id = manifest["module_id"]
        code_digest = manifest["code_digest"]
        if not code_digest:
            raise ValueError("Release 必须包含 code_digest")
        manifest_json = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_module
                    (module_id, name, enabled, status)
                VALUES (%s, %s, 0, %s)
                ON DUPLICATE KEY UPDATE name = VALUES(name), update_at = NOW()
                """,
                (module_id, manifest["name"], UserModuleStatus.DISABLED),
            )
            cursor.execute(
                """
                SELECT id FROM user_module_release
                WHERE module_id = %s AND code_digest = %s
                LIMIT 1
                """,
                (module_id, code_digest),
            )
            existing = cursor.fetchone()
            if existing:
                return int(existing["id"])
            cursor.execute(
                """
                INSERT INTO user_module_release (
                    module_id, version, code_digest, rpc_protocol,
                    driver_protocol, sdk_version, manifest_json,
                    release_path, status, compatibility_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    module_id,
                    manifest["version"],
                    code_digest,
                    manifest["rpc_protocol"],
                    manifest["driver_protocol"],
                    manifest["sdk_version"],
                    manifest_json,
                    release_path,
                    UserModuleReleaseStatus.STAGED,
                ),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def get_module(module_id: str) -> Optional[UserModuleEntity]:
        row = execute_query(
            "SELECT * FROM user_module WHERE module_id = %s LIMIT 1",
            (module_id,),
            fetch_one=True,
        )
        return UserModuleEntity.from_row(row) if row else None

    @staticmethod
    def list_modules() -> List[UserModuleEntity]:
        """返回管理后台所需的模块摘要及当前生效代码快照（软删除的模块不展示）。"""

        rows = execute_query(
            """
            SELECT
                m.*,
                active_release.version AS active_version,
                active_release.code_digest AS active_code_digest,
                active_release.status AS active_release_status,
                active_release.manifest_json AS active_manifest_json,
                (
                    SELECT COUNT(*)
                    FROM user_module_release counted_release
                    WHERE counted_release.module_id = m.module_id
                ) AS release_count
            FROM user_module m
            LEFT JOIN user_module_release active_release
                ON active_release.id = m.active_release_id
            WHERE (m.status IS NULL OR m.status <> 'deleted')
            ORDER BY m.update_at DESC, m.module_id ASC
            """,
            fetch_all=True,
        ) or []
        return [UserModuleEntity.from_row(row) for row in rows]

    @staticmethod
    def get_release(release_id: int) -> Optional[UserModuleReleaseEntity]:
        row = execute_query(
            "SELECT * FROM user_module_release WHERE id = %s LIMIT 1",
            (release_id,),
            fetch_one=True,
        )
        return UserModuleReleaseEntity.from_row(row) if row else None

    @staticmethod
    def list_releases(module_id: str) -> List[UserModuleReleaseEntity]:
        rows = execute_query(
            """
            SELECT * FROM user_module_release
            WHERE module_id = %s
            ORDER BY create_at DESC
            """,
            (module_id,),
            fetch_all=True,
        ) or []
        return [UserModuleReleaseEntity.from_row(row) for row in rows]

    @staticmethod
    def get_active_release(module_id: str) -> Optional[UserModuleReleaseEntity]:
        row = execute_query(
            """
            SELECT r.* FROM user_module m
            JOIN user_module_release r ON r.id = m.active_release_id
            WHERE m.module_id = %s AND m.enabled = 1
            LIMIT 1
            """,
            (module_id,),
            fetch_one=True,
        )
        return UserModuleReleaseEntity.from_row(row) if row else None

    @staticmethod
    def list_active_releases() -> List[UserModuleReleaseEntity]:
        rows = execute_query(
            """
            SELECT r.* FROM user_module m
            JOIN user_module_release r ON r.id = m.active_release_id
            WHERE m.enabled = 1 AND m.status = %s
            ORDER BY m.module_id
            """,
            (UserModuleStatus.ACTIVE,),
            fetch_all=True,
        ) or []
        return [UserModuleReleaseEntity.from_row(row) for row in rows]

    @staticmethod
    def list_required_releases() -> List[UserModuleReleaseEntity]:
        """加载激活版本以及仍被非终态任务引用的旧版本。"""

        terminal = ModuleJobStatus.TERMINAL
        placeholders = ", ".join(["%s"] * len(terminal))
        rows = execute_query(
            f"""
            SELECT DISTINCT r.* FROM user_module_release r
            LEFT JOIN user_module m ON m.active_release_id = r.id AND m.enabled = 1
            LEFT JOIN module_job j ON j.release_id = r.id
                AND j.status NOT IN ({placeholders})
            WHERE m.id IS NOT NULL OR j.job_id IS NOT NULL
            ORDER BY r.module_id, r.create_at
            """,
            terminal,
            fetch_all=True,
        ) or []
        return [UserModuleReleaseEntity.from_row(row) for row in rows]

    @staticmethod
    def mark_release_ready(release_id: int) -> int:
        return execute_update(
            """
            UPDATE user_module_release
            SET status = %s, compatibility_status = 'compatible', last_error = NULL,
                update_at = NOW()
            WHERE id = %s AND status IN (%s, %s)
            """,
            (
                UserModuleReleaseStatus.READY,
                release_id,
                UserModuleReleaseStatus.STAGED,
                UserModuleReleaseStatus.FAILED,
            ),
        )

    @staticmethod
    def mark_release_failed(release_id: int, error: str) -> int:
        return execute_update(
            """
            UPDATE user_module_release
            SET status = %s, compatibility_status = 'failed', last_error = %s,
                update_at = NOW()
            WHERE id = %s AND status IN (%s, %s)
            """,
            (
                UserModuleReleaseStatus.FAILED,
                error[:4000],
                release_id,
                UserModuleReleaseStatus.STAGED,
                UserModuleReleaseStatus.FAILED,
            ),
        )

    @staticmethod
    def mark_release_incompatible(release_id: int, error: str) -> int:
        return execute_update(
            """
            UPDATE user_module_release
            SET status = %s, compatibility_status = 'incompatible', last_error = %s,
                update_at = NOW()
            WHERE id = %s
            """,
            (UserModuleReleaseStatus.INCOMPATIBLE, error[:4000], release_id),
        )

    @staticmethod
    def mark_non_terminal_jobs_incompatible(release_id: int, error: str) -> int:
        terminal = ModuleJobStatus.TERMINAL
        placeholders = ", ".join(["%s"] * len(terminal))
        return execute_update(
            f"""
            UPDATE module_job
            SET status = %s, error_json = %s, next_poll_at = NULL, update_at = NOW()
            WHERE release_id = %s AND status NOT IN ({placeholders})
            """,
            (
                ModuleJobStatus.INCOMPATIBLE,
                json.dumps({"code": "MODULE_INCOMPATIBLE", "message": error}, ensure_ascii=False),
                release_id,
                *terminal,
            ),
        )

    @staticmethod
    def activate_release(module_id: str, release_id: int) -> None:
        """校验归属和状态后原子切换激活指针。"""

        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, module_id, status FROM user_module_release
                WHERE id = %s FOR UPDATE
                """,
                (release_id,),
            )
            release = cursor.fetchone()
            if not release or release["module_id"] != module_id:
                raise ValueError("Release 不存在或不属于指定模块")
            if release["status"] not in {
                UserModuleReleaseStatus.READY,
                UserModuleReleaseStatus.ACTIVE,
                UserModuleReleaseStatus.DRAINING,
            }:
                raise ValueError("Release 尚未通过兼容性和健康检查")
            cursor.execute(
                """
                UPDATE user_module_release r
                JOIN user_module m ON m.active_release_id = r.id
                SET r.status = %s, r.update_at = NOW()
                WHERE m.module_id = %s AND r.id <> %s
                """,
                (UserModuleReleaseStatus.DRAINING, module_id, release_id),
            )
            cursor.execute(
                "UPDATE user_module_release SET status = %s, update_at = NOW() WHERE id = %s",
                (UserModuleReleaseStatus.ACTIVE, release_id),
            )
            cursor.execute(
                """
                UPDATE user_module
                SET active_release_id = %s, enabled = 1, status = %s,
                    last_error = NULL, update_at = NOW()
                WHERE module_id = %s
                """,
                (release_id, UserModuleStatus.ACTIVE, module_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("模块不存在")

    @staticmethod
    def disable(module_id: str) -> int:
        return execute_update(
            """
            UPDATE user_module
            SET enabled = 0, status = %s, update_at = NOW()
            WHERE module_id = %s
            """,
            (UserModuleStatus.DISABLED, module_id),
        )

    @staticmethod
    def delete_module(module_id: str) -> int:
        """软删除：仅允许删除已禁用的模块（enabled=1 返回 0 行，由路由转 400）。

        保留 user_module/user_module_release 行与历史 module_job 记录
        （release 受 FK RESTRICT 保护）；list_modules 按 status 过滤隐藏。
        """
        return execute_update(
            """
            UPDATE user_module
            SET enabled = 0, status = %s, update_at = NOW()
            WHERE module_id = %s AND enabled = 0
            """,
            (UserModuleStatus.DELETED, module_id),
        )

    @staticmethod
    def quarantine(module_id: str, message: str) -> int:
        return execute_update(
            """
            UPDATE user_module
            SET enabled = 0, status = %s, last_error = %s, update_at = NOW()
            WHERE module_id = %s
            """,
            (UserModuleStatus.QUARANTINED, message[:4000], module_id),
        )


class ModuleJobsModel:
    @staticmethod
    def create(
        *,
        job_id: str,
        release: UserModuleReleaseEntity,
        requester_id: str,
        operation: str,
        media_kind: str,
        idempotency_key: str,
        completion_modes: List[str],
        request: Dict[str, Any],
        timeout_at: Any,
        callback_token_hash: Optional[str] = None,
    ) -> ModuleJobEntity:
        """按 requester/module/idempotency 幂等创建并钉住 Release。"""

        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO module_job (
                    job_id, release_id, module_id, module_version, code_digest,
                    protocol_version, requester_id, operation, media_kind, status,
                    idempotency_key, completion_modes, request_json, timeout_at,
                    callback_token_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE update_at = update_at
                """,
                (
                    job_id,
                    release.id,
                    release.module_id,
                    release.version,
                    release.code_digest,
                    release.driver_protocol,
                    requester_id,
                    operation,
                    media_kind,
                    ModuleJobStatus.QUEUED,
                    idempotency_key,
                    json.dumps(completion_modes, ensure_ascii=False),
                    json.dumps(request, ensure_ascii=False),
                    timeout_at,
                    callback_token_hash,
                ),
            )
            cursor.execute(
                """
                SELECT * FROM module_job
                WHERE requester_id = %s AND module_id = %s AND idempotency_key = %s
                LIMIT 1
                """,
                (requester_id, release.module_id, idempotency_key),
            )
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("创建模块任务后无法读取记录")
            return ModuleJobEntity.from_row(row)

    @staticmethod
    def get(job_id: str) -> Optional[ModuleJobEntity]:
        row = execute_query(
            "SELECT * FROM module_job WHERE job_id = %s LIMIT 1",
            (job_id,),
            fetch_one=True,
        )
        return ModuleJobEntity.from_row(row) if row else None

    @staticmethod
    def get_by_callback_token_hash(callback_token_hash: str) -> Optional[ModuleJobEntity]:
        row = execute_query(
            "SELECT * FROM module_job WHERE callback_token_hash = %s LIMIT 1",
            (callback_token_hash,),
            fetch_one=True,
        )
        return ModuleJobEntity.from_row(row) if row else None

    @staticmethod
    def list_queued(limit: int = 50) -> List[ModuleJobEntity]:
        rows = execute_query(
            """
            SELECT * FROM module_job
            WHERE status = %s AND timeout_at > UTC_TIMESTAMP()
            ORDER BY create_at ASC
            LIMIT %s
            """,
            (ModuleJobStatus.QUEUED, limit),
            fetch_all=True,
        ) or []
        return [ModuleJobEntity.from_row(row) for row in rows]

    @staticmethod
    def claim_queued(job_id: str) -> bool:
        affected = execute_update(
            """
            UPDATE module_job SET status = %s, update_at = NOW()
            WHERE job_id = %s AND status = %s
            """,
            (ModuleJobStatus.SUBMITTED, job_id, ModuleJobStatus.QUEUED),
        )
        return affected == 1

    @staticmethod
    def mark_accepted(
        job_id: str,
        external_job_id: str,
        handle: Dict[str, Any],
        next_poll_at: Any,
    ) -> int:
        return execute_update(
            """
            UPDATE module_job
            SET status = %s, external_job_id = %s, handle_json = %s,
                next_poll_at = %s, update_at = NOW()
            WHERE job_id = %s AND status IN (%s, %s)
            """,
            (
                ModuleJobStatus.RUNNING,
                external_job_id,
                json.dumps(handle, ensure_ascii=False),
                next_poll_at,
                job_id,
                ModuleJobStatus.SUBMITTED,
                ModuleJobStatus.RUNNING,
            ),
        )

    @staticmethod
    def update_running(
        job_id: str,
        *,
        progress: Optional[float],
        next_poll_at: Any,
    ) -> int:
        return execute_update(
            """
            UPDATE module_job
            SET status = %s, progress = %s, next_poll_at = %s, update_at = NOW()
            WHERE job_id = %s AND status = %s
            """,
            (
                ModuleJobStatus.RUNNING,
                progress,
                next_poll_at,
                job_id,
                ModuleJobStatus.RUNNING,
            ),
        )

    @staticmethod
    def mark_completed(job_id: str, result: Dict[str, Any]) -> int:
        return execute_update(
            """
            UPDATE module_job
            SET status = %s, progress = 1, result_json = %s, error_json = NULL,
                next_poll_at = NULL, complete_at = NOW(), update_at = NOW()
            WHERE job_id = %s AND status NOT IN (%s, %s, %s, %s)
            """,
            (
                ModuleJobStatus.SUCCEEDED,
                json.dumps(result, ensure_ascii=False),
                job_id,
                *ModuleJobStatus.TERMINAL,
            ),
        )

    @staticmethod
    def mark_failed(job_id: str, error: Dict[str, Any], *, timed_out: bool = False) -> int:
        status = ModuleJobStatus.TIMED_OUT if timed_out else ModuleJobStatus.FAILED
        return execute_update(
            """
            UPDATE module_job
            SET status = %s, error_json = %s, next_poll_at = NULL,
                complete_at = NOW(), update_at = NOW()
            WHERE job_id = %s AND status NOT IN (%s, %s, %s, %s)
            """,
            (status, json.dumps(error, ensure_ascii=False), job_id, *ModuleJobStatus.TERMINAL),
        )

    @staticmethod
    def retry_submission(job_id: str, error: Dict[str, Any]) -> int:
        return execute_update(
            """
            UPDATE module_job
            SET status = %s, error_json = %s, update_at = NOW()
            WHERE job_id = %s AND status = %s AND timeout_at > UTC_TIMESTAMP()
            """,
            (
                ModuleJobStatus.QUEUED,
                json.dumps(error, ensure_ascii=False),
                job_id,
                ModuleJobStatus.SUBMITTED,
            ),
        )

    @staticmethod
    def retry_poll(job_id: str, error: Dict[str, Any], next_poll_at: Any) -> int:
        return execute_update(
            """
            UPDATE module_job
            SET error_json = %s, next_poll_at = %s, update_at = NOW()
            WHERE job_id = %s AND status = %s AND timeout_at > UTC_TIMESTAMP()
            """,
            (
                json.dumps(error, ensure_ascii=False),
                next_poll_at,
                job_id,
                ModuleJobStatus.RUNNING,
            ),
        )

    @staticmethod
    def cancel(job_id: str) -> int:
        return execute_update(
            """
            UPDATE module_job
            SET status = %s, next_poll_at = NULL, complete_at = NOW(), update_at = NOW()
            WHERE job_id = %s AND status NOT IN (%s, %s, %s, %s)
            """,
            (ModuleJobStatus.CANCELLED, job_id, *ModuleJobStatus.TERMINAL),
        )

    @staticmethod
    def list_due(limit: int = 50) -> List[ModuleJobEntity]:
        rows = execute_query(
            """
            SELECT * FROM module_job
            WHERE status = %s AND next_poll_at IS NOT NULL AND next_poll_at <= UTC_TIMESTAMP()
              AND timeout_at > UTC_TIMESTAMP()
            ORDER BY next_poll_at ASC
            LIMIT %s
            """,
            (ModuleJobStatus.RUNNING, limit),
            fetch_all=True,
        ) or []
        return [ModuleJobEntity.from_row(row) for row in rows]

    @staticmethod
    def list_expired(limit: int = 50) -> List[ModuleJobEntity]:
        placeholders = ", ".join(["%s"] * len(ModuleJobStatus.TERMINAL))
        rows = execute_query(
            f"""
            SELECT * FROM module_job
            WHERE timeout_at <= UTC_TIMESTAMP() AND status NOT IN ({placeholders})
            ORDER BY timeout_at ASC
            LIMIT %s
            """,
            (*ModuleJobStatus.TERMINAL, limit),
            fetch_all=True,
        ) or []
        return [ModuleJobEntity.from_row(row) for row in rows]

    @staticmethod
    def count_non_terminal_for_release(release_id: int) -> int:
        placeholders = ", ".join(["%s"] * len(ModuleJobStatus.TERMINAL))
        row = execute_query(
            f"""
            SELECT COUNT(*) AS count FROM module_job
            WHERE release_id = %s AND status NOT IN ({placeholders})
            """,
            (release_id, *ModuleJobStatus.TERMINAL),
            fetch_one=True,
        )
        return int(row["count"]) if row else 0


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `user_module` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `module_id` VARCHAR(128) NOT NULL,
  `name` VARCHAR(128) NOT NULL,
  `enabled` TINYINT(1) NOT NULL DEFAULT 0,
  `active_release_id` BIGINT DEFAULT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'disabled',
  `last_error` TEXT DEFAULT NULL,
  `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_module_module_id` (`module_id`),
  KEY `idx_user_module_active_release` (`active_release_id`),
  KEY `idx_user_module_enabled_status` (`enabled`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `user_module_release` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `module_id` VARCHAR(128) NOT NULL,
  `version` VARCHAR(64) NOT NULL,
  `code_digest` VARCHAR(80) NOT NULL,
  `rpc_protocol` VARCHAR(64) NOT NULL,
  `driver_protocol` VARCHAR(64) NOT NULL,
  `sdk_version` VARCHAR(32) NOT NULL,
  `manifest_json` JSON NOT NULL,
  `release_path` VARCHAR(1024) NOT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'staged',
  `compatibility_status` VARCHAR(32) NOT NULL DEFAULT 'pending',
  `last_error` TEXT DEFAULT NULL,
  `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_module_release_digest` (`module_id`, `code_digest`),
  KEY `idx_user_module_release_status` (`module_id`, `status`),
  CONSTRAINT `fk_user_module_release_module` FOREIGN KEY (`module_id`)
    REFERENCES `user_module` (`module_id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `module_job` (
  `job_id` VARCHAR(64) NOT NULL,
  `release_id` BIGINT NOT NULL,
  `module_id` VARCHAR(128) NOT NULL,
  `module_version` VARCHAR(64) NOT NULL,
  `code_digest` VARCHAR(80) NOT NULL,
  `protocol_version` VARCHAR(64) NOT NULL,
  `requester_id` VARCHAR(64) NOT NULL,
  `operation` VARCHAR(100) NOT NULL,
  `media_kind` VARCHAR(16) NOT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'queued',
  `idempotency_key` VARCHAR(128) NOT NULL,
  `completion_modes` JSON NOT NULL,
  `request_json` JSON NOT NULL,
  `external_job_id` VARCHAR(512) DEFAULT NULL,
  `handle_json` JSON DEFAULT NULL,
  `result_json` JSON DEFAULT NULL,
  `error_json` JSON DEFAULT NULL,
  `progress` DECIMAL(6,5) DEFAULT NULL,
  `next_poll_at` DATETIME DEFAULT NULL,
  `timeout_at` DATETIME NOT NULL,
  `callback_token_hash` CHAR(64) DEFAULT NULL,
  `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `complete_at` DATETIME DEFAULT NULL,
  PRIMARY KEY (`job_id`),
  UNIQUE KEY `uk_module_job_idempotency` (`requester_id`, `module_id`, `idempotency_key`),
  UNIQUE KEY `uk_module_job_callback_token` (`callback_token_hash`),
  KEY `idx_module_job_due` (`status`, `next_poll_at`),
  KEY `idx_module_job_release_status` (`release_id`, `status`),
  KEY `idx_module_job_module_create` (`module_id`, `create_at`),
  CONSTRAINT `fk_module_job_release` FOREIGN KEY (`release_id`)
    REFERENCES `user_module_release` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""
