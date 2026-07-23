"""Add immutable media generation context to agent tasks.

Revision ID: 20260722_agent_media_ctx
Revises: 20260710_slots_keyindex
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

revision: str = "20260722_agent_media_ctx"
down_revision: Union[str, None] = "20260710_slots_keyindex"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table "
            "AND COLUMN_NAME = :column"
        ),
        {"table": table, "column": column},
    )
    return result.scalar() > 0


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "agent_tasks", "execution_context_json"):
        conn.execute(
            text(
                "ALTER TABLE `agent_tasks` "
                "ADD COLUMN `execution_context_json` JSON DEFAULT NULL "
                "COMMENT '不可变任务执行上下文（含媒体模型快照）' "
                "AFTER `language`"
            )
        )
        logger.info("[Migration] Added agent_tasks.execution_context_json")


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "agent_tasks", "execution_context_json"):
        conn.execute(text("ALTER TABLE `agent_tasks` DROP COLUMN `execution_context_json`"))
        logger.info("[Migration] Dropped agent_tasks.execution_context_json")
