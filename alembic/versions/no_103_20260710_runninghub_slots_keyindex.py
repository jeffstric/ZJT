"""Add api_key_index to runninghub_slots for multi-key rotation

RunningHub 多密钥轮换支持：在并发槽位表记录每个任务使用的是哪个密钥，
以便轮询结果时用同一密钥查询（错误密钥无法获取结果）。

- api_key_index: 所用密钥序号。0=全局兜底密钥(runninghub.api_key)，1~10=密钥池第N个

仅新增一列，不新建表。

Revision ID: 20260710_slots_keyindex
Revises: 20260713_asset_media_map
Create Date: 2026-07-10
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260710_slots_keyindex'
down_revision: Union[str, None] = '20260713_asset_media_map'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists in a table"""
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    return result.scalar() > 0


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, 'runninghub_slots', 'api_key_index'):
        conn.execute(text(
            "ALTER TABLE `runninghub_slots` "
            "ADD COLUMN `api_key_index` int NOT NULL DEFAULT 0 "
            "COMMENT '所用密钥序号: 0=全局key(runninghub.api_key), 1~10=密钥池第N个' "
            "AFTER `task_type`"
        ))
        logger.info("Added column runninghub_slots.api_key_index")
    else:
        logger.info("Column runninghub_slots.api_key_index already exists, skipping")


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, 'runninghub_slots', 'api_key_index'):
        conn.execute(text("ALTER TABLE `runninghub_slots` DROP COLUMN `api_key_index`"))
        logger.info("Dropped column runninghub_slots.api_key_index")
