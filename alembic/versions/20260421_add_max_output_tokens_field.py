"""Add max_output_tokens field to model table

Revision ID: 20260421_add_max_output_tokens
Revises: 20260421_add_qwen_plus
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260421_add_max_output_tokens'
down_revision: Union[str, None] = '20260421_add_qwen_plus'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add max_output_tokens field to model table and set specific values for qwen-plus"""
    conn = op.get_bind()

    # 1. 为 model 表添加 max_output_tokens 字段（默认 64000）
    conn.execute(text("""
        ALTER TABLE `model`
        ADD COLUMN `max_output_tokens` int DEFAULT 64000
        COMMENT '最大输出token数（默认64000）'
        AFTER `supports_tools`
    """))
    logger.info("[Migration] Added max_output_tokens column to model table with default value 64000")

    # 2. 针对 qwen-plus 模型设置 max_output_tokens = 32768
    conn.execute(text("""
        UPDATE `model`
        SET `max_output_tokens` = 32768
        WHERE `model_name` = 'qwen-plus'
    """))
    logger.info("[Migration] Set qwen-plus model max_output_tokens to 32768")


def downgrade() -> None:
    """Remove max_output_tokens field from model table"""
    conn = op.get_bind()

    # 删除 max_output_tokens 字段
    conn.execute(text("""
        ALTER TABLE `model`
        DROP COLUMN `max_output_tokens`
    """))
    logger.info("[Migration] Removed max_output_tokens column from model table")
    logger.info("[Migration] Reverted qwen-plus model max_output_tokens setting")
