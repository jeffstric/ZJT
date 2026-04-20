"""Add thinking fields to agent_tasks table

Revision ID: 20260421_add_thinking_fields_to_agent_tasks
Revises: 20260421_add_max_output_tokens
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260421_add_thinking_fields_to_agent_tasks'
down_revision: Union[str, None] = '20260420_add_thinking'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add enable_thinking and thinking_effort columns to agent_tasks table"""
    conn = op.get_bind()

    # Add enable_thinking column
    conn.execute(text("""
        ALTER TABLE `agent_tasks`
        ADD COLUMN `enable_thinking` tinyint(1) NOT NULL DEFAULT '0'
        COMMENT 'Whether thinking mode is enabled'
        AFTER `model_id`
    """))
    logger.info("[Migration] Added enable_thinking column to agent_tasks table")

    # Add thinking_effort column
    conn.execute(text("""
        ALTER TABLE `agent_tasks`
        ADD COLUMN `thinking_effort` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT 'medium'
        COMMENT 'Thinking effort level (low/medium/high)'
        AFTER `enable_thinking`
    """))
    logger.info("[Migration] Added thinking_effort column to agent_tasks table")


def downgrade() -> None:
    """Remove thinking fields from agent_tasks table"""
    conn = op.get_bind()

    conn.execute(text("""
        ALTER TABLE `agent_tasks`
        DROP COLUMN `thinking_effort`
    """))
    logger.info("[Migration] Removed thinking_effort column from agent_tasks table")

    conn.execute(text("""
        ALTER TABLE `agent_tasks`
        DROP COLUMN `enable_thinking`
    """))
    logger.info("[Migration] Removed enable_thinking column from agent_tasks table")
