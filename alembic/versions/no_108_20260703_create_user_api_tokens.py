"""Create user_api_tokens

Revision ID: 20260703_user_api_tokens
Revises: 20260701_storyboard_version
Create Date: 2026-07-03
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)


revision: str = '20260703_user_api_tokens'
down_revision: Union[str, None] = '20260701_storyboard_version'
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
    if _table_exists(conn, "user_api_tokens"):
        logger.info("[Migration] user_api_tokens already exists")
        return

    conn.execute(text("""
        CREATE TABLE `user_api_tokens` (
          `id` INT NOT NULL AUTO_INCREMENT,
          `user_id` INT NOT NULL,
          `token_hash` CHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
          `token_prefix` VARCHAR(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
          `token_type` VARCHAR(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'agent',
          `scopes` JSON DEFAULT NULL,
          `enabled` TINYINT(1) NOT NULL DEFAULT 1,
          `expire_at` DATETIME DEFAULT NULL,
          `last_used_at` DATETIME DEFAULT NULL,
          `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (`id`),
          UNIQUE KEY `idx_user_api_token_hash` (`token_hash`),
          KEY `idx_user_api_tokens_user` (`user_id`),
          KEY `idx_user_api_tokens_type` (`token_type`),
          KEY `idx_user_api_tokens_expire` (`expire_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User API tokens for agents and integrations'
    """))
    logger.info("[Migration] Created user_api_tokens")


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "user_api_tokens"):
        conn.execute(text("DROP TABLE `user_api_tokens`"))
        logger.info("[Migration] Dropped user_api_tokens")
