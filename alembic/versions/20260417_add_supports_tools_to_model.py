"""Add supports_tools field to model table

Revision ID: 20260417_supports_tools
Revises: 20260417_ctx_window_model
Create Date: 2026-04-17

Add supports_tools field to model table for Ollama Tool Calling support.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.sql import text
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260417_supports_tools'
down_revision: Union[str, None] = '20260417_ctx_window_model'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add supports_tools field to model table"""
    op.execute(text("""
        ALTER TABLE `model`
        ADD COLUMN `supports_tools` TINYINT(1) DEFAULT 1 COMMENT '是否支持 Tool Calling'
        AFTER `context_window`
    """))
    logger.info("[Migration] Added supports_tools field to model table")


def downgrade() -> None:
    """Remove supports_tools field from model table"""
    op.execute(text("""
        ALTER TABLE `model`
        DROP COLUMN `supports_tools`
    """))
    logger.info("[Migration] Removed supports_tools field from model table")
