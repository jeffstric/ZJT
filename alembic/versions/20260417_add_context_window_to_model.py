"""Add context_window to model table

Revision ID: 20260417_add_context_window_to_model
Revises: 20260416_daily_checkin
Create Date: 2026-04-17

Add context_window field to model table for storing model context window size.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.sql import text
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260417_ctx_window_model'
down_revision: Union[str, None] = '20260416_daily_checkin'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add context_window field to model table and backfill known models"""
    op.execute(text("""
        ALTER TABLE `model`
        ADD COLUMN `context_window` INT DEFAULT NULL COMMENT '模型上下文窗口大小（token数）'
        AFTER `model_name`
    """))
    logger.info("[Migration] Added context_window field to model table")

    # Backfill known models with their context window sizes
    # Mapping: model_name substring -> context_window
    # These are approximate values for common models in the system.
    MODEL_CONTEXT_WINDOWS = {
        'gemini-3-flash-preview': 1048576,
        'gemini-3.1-pro-preview': 1048576,
        'gemini-3.1-flash-lite': 1048576,
        'qwen3.5-plus': 991000,
        'qwen3.6-plus': 991000,
    }

    for model_substring, ctx_window in MODEL_CONTEXT_WINDOWS.items():
        op.execute(text(f"""
            UPDATE `model`
            SET `context_window` = {ctx_window}
            WHERE `model_name` LIKE '%{model_substring}%'
        """))
        logger.info(f"[Migration] Backfilled context_window={ctx_window} for models matching '%{model_substring}%'")


def downgrade() -> None:
    """Remove context_window field from model table"""
    op.execute(text("""
        ALTER TABLE `model`
        DROP COLUMN `context_window`
    """))
    logger.info("[Migration] Removed context_window field from model table")
