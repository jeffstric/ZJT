"""Add story_type to world

Revision ID: 20260701_world_story_type
Revises: 20260624_storyboard_v2
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)


revision: str = '20260701_world_story_type'
down_revision: Union[str, None] = '20260624_storyboard_v2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    return result.scalar() > 0


def upgrade() -> None:
    """Add world story_type and backfill existing rows as dialogue."""
    conn = op.get_bind()

    if not _column_exists(conn, 'world', 'story_type'):
        conn.execute(text("""
            ALTER TABLE `world`
            ADD COLUMN `story_type` varchar(32) NOT NULL DEFAULT 'dialogue'
            COMMENT '故事类型：dialogue=对话剧情,narration=旁白解说,music_mv=音乐MV'
            AFTER `story_outline`
        """))
        logger.info("[Migration] Added world.story_type")

    conn.execute(text("""
        UPDATE `world`
        SET `story_type` = 'dialogue'
        WHERE `story_type` IS NULL OR `story_type` = ''
    """))
    logger.info("[Migration] Backfilled world.story_type as dialogue")


def downgrade() -> None:
    """Remove world story_type."""
    conn = op.get_bind()

    if _column_exists(conn, 'world', 'story_type'):
        conn.execute(text("ALTER TABLE `world` DROP COLUMN `story_type`"))
        logger.info("[Migration] Removed world.story_type")
