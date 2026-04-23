"""Add supports_thinking field to model table

为 model 表新增 supports_thinking 字段，标记模型是否支持思考模式。
批量更新非 Gemini 模型为支持思考模式。

Revision ID: 20260420_add_thinking
Revises: 20260420_add_volcengine_doubao
Create Date: 2026-04-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260420_add_thinking'
down_revision: Union[str, None] = '20260420_add_volcengine_doubao'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add supports_thinking column and update existing models"""
    # 1. 添加字段
    op.add_column('model', sa.Column(
        'supports_thinking',
        sa.Boolean(),
        nullable=False,
        server_default=sa.text('0'),
        comment='是否支持思考模式'
    ))
    logger.info("[Migration] Added supports_thinking column to model table")

    # 2. 批量更新：非 Gemini 模型支持思考模式
    op.execute(sa.text("""
        UPDATE `model` SET supports_thinking = 1
        WHERE model_name NOT LIKE 'gemini%'
    """))
    logger.info("[Migration] Updated non-Gemini models to support thinking")


def downgrade() -> None:
    """Remove supports_thinking column"""
    op.drop_column('model', 'supports_thinking')
    logger.info("[Migration] Removed supports_thinking column from model table")
