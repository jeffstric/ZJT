"""Storyboard image batch orchestration queue."""
import json
import logging
from typing import Any, Dict, List, Optional

from config.constant import StoryboardAutoGenerateConstants
from .database import execute_insert, execute_query, execute_update

logger = logging.getLogger(__name__)


def _json_dumps(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _datetime_to_text(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


class StoryboardImageBatchJobModel:
    """Database operations for storyboard_image_batch_job."""

    _JSON_FIELDS = {"extra_json"}

    @staticmethod
    def _normalize(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        data = dict(row)
        data["extra_json"] = _json_loads(data.get("extra_json"), {})
        data["create_at"] = _datetime_to_text(data.get("create_at"))
        data["update_at"] = _datetime_to_text(data.get("update_at"))
        return data

    @staticmethod
    def create(**kwargs: Any) -> int:
        fields = [
            "storyboard_id",
            "user_id",
            "auth_token",
            "asset_type",
            "sequence_mode",
            "mode",
            "prompt",
            "source_image",
            "ratio",
            "image_size",
            "count",
            "limit_count",
            "stop_on_error",
            "status",
            "extra_json",
        ]
        values = []
        for field in fields:
            value = kwargs.get(field)
            values.append(_json_dumps(value) if field in StoryboardImageBatchJobModel._JSON_FIELDS else value)
        placeholders = ", ".join(["%s"] * len(fields))
        sql = f"""
            INSERT INTO storyboard_image_batch_job
            ({", ".join(fields)})
            VALUES ({placeholders})
        """
        return execute_insert(sql, tuple(values))

    @staticmethod
    def get_by_id(record_id: int) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM storyboard_image_batch_job WHERE id = %s"
        row = execute_query(sql, (record_id,), fetch_one=True)
        return StoryboardImageBatchJobModel._normalize(row)

    @staticmethod
    def list_active(limit: int = 10) -> List[Dict[str, Any]]:
        sql = """
            SELECT * FROM storyboard_image_batch_job
            WHERE status IN (%s, %s)
            ORDER BY id ASC
            LIMIT %s
        """
        rows = execute_query(
            sql,
            (
                StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_PENDING,
                StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_RUNNING,
                int(limit),
            ),
            fetch_all=True,
        ) or []
        return [StoryboardImageBatchJobModel._normalize(row) for row in rows]

    @staticmethod
    def list_active_by_storyboard(
        storyboard_id: int,
        *,
        asset_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        filters = [
            "storyboard_id = %s",
            "status IN (%s, %s)",
        ]
        params: List[Any] = [
            int(storyboard_id),
            StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_PENDING,
            StoryboardAutoGenerateConstants.BATCH_JOB_STATUS_RUNNING,
        ]
        if asset_type:
            filters.append("asset_type = %s")
            params.append(asset_type)
        params.append(int(limit))
        sql = f"""
            SELECT * FROM storyboard_image_batch_job
            WHERE {' AND '.join(filters)}
            ORDER BY id ASC
            LIMIT %s
        """
        rows = execute_query(sql, tuple(params), fetch_all=True) or []
        return [StoryboardImageBatchJobModel._normalize(row) for row in rows]

    @staticmethod
    def update(record_id: int, **kwargs: Any) -> int:
        allowed = {
            "status",
            "submitted_count",
            "completed_count",
            "failed_count",
            "skipped_count",
            "message",
            "extra_json",
        }
        fields = []
        params = []
        for key, value in kwargs.items():
            if key not in allowed:
                continue
            fields.append(f"{key} = %s")
            params.append(_json_dumps(value) if key in StoryboardImageBatchJobModel._JSON_FIELDS else value)
        if not fields:
            return 0
        params.append(record_id)
        sql = f"UPDATE storyboard_image_batch_job SET {', '.join(fields)} WHERE id = %s"
        return execute_update(sql, tuple(params))


class StoryboardImageBatchItemModel:
    """Database operations for storyboard_image_batch_item."""

    _JSON_FIELDS = {"project_ids", "extra_json"}

    @staticmethod
    def _normalize(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        data = dict(row)
        data["project_ids"] = _json_loads(data.get("project_ids"), [])
        data["extra_json"] = _json_loads(data.get("extra_json"), {})
        data["create_at"] = _datetime_to_text(data.get("create_at"))
        data["update_at"] = _datetime_to_text(data.get("update_at"))
        return data

    @staticmethod
    def create(**kwargs: Any) -> int:
        fields = [
            "job_id",
            "storyboard_id",
            "scene_id",
            "asset_type",
            "group_key",
            "order_index",
            "dependency_item_id",
            "status",
            "ai_tool_id",
            "asset_id",
            "project_ids",
            "reference_item_id",
            "reference_url",
            "result_url",
            "error_code",
            "error_message",
            "extra_json",
        ]
        values = []
        for field in fields:
            value = kwargs.get(field)
            values.append(_json_dumps(value) if field in StoryboardImageBatchItemModel._JSON_FIELDS else value)
        sql = f"""
            INSERT INTO storyboard_image_batch_item
            ({", ".join(fields)})
            VALUES ({", ".join(["%s"] * len(fields))})
        """
        return execute_insert(sql, tuple(values))

    @staticmethod
    def get_by_id(record_id: int) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM storyboard_image_batch_item WHERE id = %s"
        row = execute_query(sql, (record_id,), fetch_one=True)
        return StoryboardImageBatchItemModel._normalize(row)

    @staticmethod
    def list_by_job(job_id: int) -> List[Dict[str, Any]]:
        sql = """
            SELECT * FROM storyboard_image_batch_item
            WHERE job_id = %s
            ORDER BY order_index ASC, id ASC
        """
        rows = execute_query(sql, (job_id,), fetch_all=True) or []
        return [StoryboardImageBatchItemModel._normalize(row) for row in rows]

    @staticmethod
    def find_running_by_grid_task(grid_task_id: int, scene_id: int) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT * FROM storyboard_image_batch_item
            WHERE scene_id = %s
              AND status = %s
              AND JSON_EXTRACT(extra_json, '$.grid_task_id') = %s
            LIMIT 1
        """
        row = execute_query(
            sql,
            (
                int(scene_id),
                StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_RUNNING,
                int(grid_task_id),
            ),
            fetch_one=True,
        )
        return StoryboardImageBatchItemModel._normalize(row)

    @staticmethod
    def find_by_grid_task(grid_task_id: int, scene_id: int) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT * FROM storyboard_image_batch_item
            WHERE scene_id = %s
              AND JSON_EXTRACT(extra_json, '$.grid_task_id') = %s
            ORDER BY id DESC
            LIMIT 1
        """
        row = execute_query(
            sql,
            (
                int(scene_id),
                int(grid_task_id),
            ),
            fetch_one=True,
        )
        return StoryboardImageBatchItemModel._normalize(row)

    @staticmethod
    def update(record_id: int, **kwargs: Any) -> int:
        allowed = {
            "status",
            "ai_tool_id",
            "asset_id",
            "project_ids",
            "reference_item_id",
            "reference_url",
            "result_url",
            "error_code",
            "error_message",
            "extra_json",
        }
        fields = []
        params = []
        for key, value in kwargs.items():
            if key not in allowed:
                continue
            fields.append(f"{key} = %s")
            params.append(_json_dumps(value) if key in StoryboardImageBatchItemModel._JSON_FIELDS else value)
        if not fields:
            return 0
        params.append(record_id)
        sql = f"UPDATE storyboard_image_batch_item SET {', '.join(fields)} WHERE id = %s"
        return execute_update(sql, tuple(params))


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `storyboard_image_batch_job` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `storyboard_id` INT UNSIGNED NOT NULL,
  `user_id` INT UNSIGNED NOT NULL,
  `auth_token` TEXT DEFAULT NULL,
  `asset_type` VARCHAR(32) NOT NULL DEFAULT 'first_frame',
  `sequence_mode` VARCHAR(32) NOT NULL DEFAULT 'balanced',
  `mode` VARCHAR(32) NOT NULL DEFAULT 'auto',
  `prompt` TEXT DEFAULT NULL,
  `source_image` VARCHAR(1024) DEFAULT NULL,
  `ratio` VARCHAR(32) DEFAULT NULL,
  `image_size` VARCHAR(32) DEFAULT NULL,
  `count` INT NOT NULL DEFAULT 1,
  `limit_count` INT NOT NULL DEFAULT 5,
  `stop_on_error` TINYINT(1) NOT NULL DEFAULT 1,
  `status` TINYINT NOT NULL DEFAULT 0,
  `submitted_count` INT NOT NULL DEFAULT 0,
  `completed_count` INT NOT NULL DEFAULT 0,
  `failed_count` INT NOT NULL DEFAULT 0,
  `skipped_count` INT NOT NULL DEFAULT 0,
  `message` VARCHAR(512) DEFAULT NULL,
  `extra_json` JSON DEFAULT NULL,
  `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_storyboard_image_batch_job_active` (`status`, `id`),
  KEY `idx_storyboard_image_batch_job_storyboard` (`storyboard_id`, `create_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Storyboard image batch orchestration jobs';

CREATE TABLE IF NOT EXISTS `storyboard_image_batch_item` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `job_id` INT UNSIGNED NOT NULL,
  `storyboard_id` INT UNSIGNED NOT NULL,
  `scene_id` INT UNSIGNED NOT NULL,
  `asset_type` VARCHAR(32) NOT NULL DEFAULT 'first_frame',
  `group_key` VARCHAR(128) DEFAULT NULL,
  `order_index` INT NOT NULL DEFAULT 0,
  `dependency_item_id` INT UNSIGNED DEFAULT NULL,
  `status` TINYINT NOT NULL DEFAULT 0,
  `ai_tool_id` INT DEFAULT NULL,
  `asset_id` INT DEFAULT NULL,
  `project_ids` JSON DEFAULT NULL,
  `reference_item_id` INT UNSIGNED DEFAULT NULL,
  `reference_url` VARCHAR(1024) DEFAULT NULL,
  `result_url` VARCHAR(1024) DEFAULT NULL,
  `error_code` VARCHAR(64) DEFAULT NULL,
  `error_message` VARCHAR(512) DEFAULT NULL,
  `extra_json` JSON DEFAULT NULL,
  `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_storyboard_image_batch_item_job` (`job_id`, `status`, `order_index`),
  KEY `idx_storyboard_image_batch_item_scene` (`storyboard_id`, `scene_id`),
  KEY `idx_storyboard_image_batch_item_dependency` (`dependency_item_id`),
  CONSTRAINT `fk_storyboard_image_batch_item_job`
    FOREIGN KEY (`job_id`) REFERENCES `storyboard_image_batch_job`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Storyboard image batch orchestration items';
"""


__all__ = ["StoryboardImageBatchJobModel", "StoryboardImageBatchItemModel"]
