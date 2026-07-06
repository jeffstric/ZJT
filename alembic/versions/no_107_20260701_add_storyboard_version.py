"""Add version to storyboard

Revision ID: 20260701_storyboard_version
Revises: 20260701_world_story_type
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)


revision: str = '20260701_storyboard_version'
down_revision: Union[str, None] = '20260701_world_story_type'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    return result.scalar() > 0


def upgrade() -> None:
    """Add storyboard.version and backfill existing rows as version 1."""
    conn = op.get_bind()

    if not _column_exists(conn, 'storyboard', 'version'):
        conn.execute(text("""
            ALTER TABLE `storyboard`
            ADD COLUMN `version` INT NOT NULL DEFAULT 1
            COMMENT '版本号'
            AFTER `id`
        """))
        logger.info("[Migration] Added storyboard.version")

    conn.execute(text("""
        UPDATE `storyboard`
        SET `version` = 1
        WHERE `version` IS NULL OR `version` < 1
    """))
    logger.info("[Migration] Backfilled storyboard.version as 1")


def downgrade() -> None:
    """Remove storyboard.version."""
    conn = op.get_bind()

    if _column_exists(conn, 'storyboard', 'version'):
        conn.execute(text("ALTER TABLE `storyboard` DROP COLUMN `version`"))
        logger.info("[Migration] Removed storyboard.version")
