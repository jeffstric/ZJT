"""Add world soft-delete fields (is_deleted, deleted_at)

Revision ID: 20260812_world_soft_del
Revises: 20260810_add_agnes
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260812_world_soft_del'
down_revision: Union[str, None] = '20260810_add_agnes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    return result.scalar() > 0


def _index_exists(conn, table: str, index: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :index"
    ), {"table": table, "index": index})
    return result.scalar() > 0


def upgrade() -> None:
    """Add world.is_deleted / world.deleted_at for soft-delete (hide) support."""
    conn = op.get_bind()

    if not _column_exists(conn, 'world', 'is_deleted'):
        conn.execute(text("""
            ALTER TABLE `world`
            ADD COLUMN `is_deleted` tinyint(1) NOT NULL DEFAULT 0
            COMMENT '伪删除：0=正常展示，1=从列表隐藏'
            AFTER `workspace_id`
        """))
        logger.info("[Migration] Added world.is_deleted")

    if not _column_exists(conn, 'world', 'deleted_at'):
        conn.execute(text("""
            ALTER TABLE `world`
            ADD COLUMN `deleted_at` datetime NULL DEFAULT NULL
            COMMENT '伪删除时间；恢复时置空'
            AFTER `is_deleted`
        """))
        logger.info("[Migration] Added world.deleted_at")

    if not _index_exists(conn, 'world', 'idx_user_deleted'):
        conn.execute(text(
            "CREATE INDEX `idx_user_deleted` ON `world` (`user_id`, `is_deleted`)"
        ))
        logger.info("[Migration] Added index idx_user_deleted on world")


def downgrade() -> None:
    """Remove world soft-delete fields."""
    conn = op.get_bind()

    if _index_exists(conn, 'world', 'idx_user_deleted'):
        conn.execute(text("DROP INDEX `idx_user_deleted` ON `world`"))
        logger.info("[Migration] Dropped index idx_user_deleted")

    if _column_exists(conn, 'world', 'deleted_at'):
        conn.execute(text("ALTER TABLE `world` DROP COLUMN `deleted_at`"))
        logger.info("[Migration] Removed world.deleted_at")

    if _column_exists(conn, 'world', 'is_deleted'):
        conn.execute(text("ALTER TABLE `world` DROP COLUMN `is_deleted`"))
        logger.info("[Migration] Removed world.is_deleted")
