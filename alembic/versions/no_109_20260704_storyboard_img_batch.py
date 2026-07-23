"""Create storyboard image batch queue

Revision ID: 20260704_storyboard_img_batch
Revises: 20260703_user_api_tokens
Create Date: 2026-07-04
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)


revision: str = '20260704_storyboard_img_batch'
down_revision: Union[str, None] = '20260703_user_api_tokens'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table"
    ), {"table": table})
    return result.scalar() > 0


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "storyboard_image_batch_job"):
        conn.execute(text("""
            CREATE TABLE `storyboard_image_batch_job` (
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
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Storyboard image batch orchestration jobs'
        """))
        logger.info("[Migration] Created storyboard_image_batch_job")

    if not _table_exists(conn, "storyboard_image_batch_item"):
        conn.execute(text("""
            CREATE TABLE `storyboard_image_batch_item` (
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
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Storyboard image batch orchestration items'
        """))
        logger.info("[Migration] Created storyboard_image_batch_item")


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "storyboard_image_batch_item"):
        conn.execute(text("DROP TABLE `storyboard_image_batch_item`"))
        logger.info("[Migration] Dropped storyboard_image_batch_item")
    if _table_exists(conn, "storyboard_image_batch_job"):
        conn.execute(text("DROP TABLE `storyboard_image_batch_job`"))
        logger.info("[Migration] Dropped storyboard_image_batch_job")
