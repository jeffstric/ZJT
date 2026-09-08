"""add vendor id to chat sessions

Revision ID: 20260904_add_vendor_id_to_chat_s
Revises: 20260901_merge_ds_heads
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260904_add_vendor_id_to_chat_s'
down_revision: Union[str, None] = '20260901_merge_ds_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists in a table"""
    result = conn.execute(text(
        f"SELECT COUNT(*) FROM information_schema.COLUMNS "
        f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    return result.scalar() > 0


def upgrade() -> None:
    """为 chat_sessions 表新增 vendor_id 列，持久化会话选择的供应商 ID"""
    conn = op.get_bind()

    if not _column_exists(conn, 'chat_sessions', 'vendor_id'):
        conn.execute(text(
            "ALTER TABLE `chat_sessions` ADD COLUMN `vendor_id` int DEFAULT NULL "
            "COMMENT 'Vendor ID for the selected model' AFTER `model_id`"
        ))
        logger.info("[Migration] Added column `vendor_id` to chat_sessions table")
    else:
        logger.info("[Migration] Column `vendor_id` already exists, skipped")


def downgrade() -> None:
    """移除 chat_sessions.vendor_id 列"""
    conn = op.get_bind()

    if _column_exists(conn, 'chat_sessions', 'vendor_id'):
        conn.execute(text("ALTER TABLE `chat_sessions` DROP COLUMN `vendor_id`"))
        logger.info("[Migration] Removed column `vendor_id` from chat_sessions table")
