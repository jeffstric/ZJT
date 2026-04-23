"""Add thinking fields to agent_tasks table

Revision ID: 20260421_agent_task_thinking
Revises: 20260420_add_thinking
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260421_agent_task_thinking'
down_revision: Union[str, None] = '20260420_add_thinking'
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
    """Add enable_thinking and thinking_effort columns to agent_tasks table"""
    conn = op.get_bind()

    if not _column_exists(conn, 'agent_tasks', 'enable_thinking'):
        conn.execute(text("""
            ALTER TABLE `agent_tasks`
            ADD COLUMN `enable_thinking` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'false'
            COMMENT 'Thinking mode: true/false/auto'
            AFTER `model_id`
        """))
        logger.info("[Migration] Added enable_thinking column to agent_tasks table")
    else:
        logger.info("[Migration] Column enable_thinking already exists, skipped")

    if not _column_exists(conn, 'agent_tasks', 'thinking_effort'):
        conn.execute(text("""
            ALTER TABLE `agent_tasks`
            ADD COLUMN `thinking_effort` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT 'medium'
            COMMENT 'Thinking effort level (low/medium/high)'
            AFTER `enable_thinking`
        """))
        logger.info("[Migration] Added thinking_effort column to agent_tasks table")
    else:
        logger.info("[Migration] Column thinking_effort already exists, skipped")


def downgrade() -> None:
    """Remove thinking fields from agent_tasks table"""
    conn = op.get_bind()

    if _column_exists(conn, 'agent_tasks', 'thinking_effort'):
        conn.execute(text("ALTER TABLE `agent_tasks` DROP COLUMN `thinking_effort`"))
        logger.info("[Migration] Removed thinking_effort column from agent_tasks table")

    if _column_exists(conn, 'agent_tasks', 'enable_thinking'):
        conn.execute(text("ALTER TABLE `agent_tasks` DROP COLUMN `enable_thinking`"))
        logger.info("[Migration] Removed enable_thinking column from agent_tasks table")
