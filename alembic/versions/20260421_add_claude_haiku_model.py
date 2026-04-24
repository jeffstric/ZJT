"""Add Claude vendor and claude-haiku-4-5 model

Revision ID: 20260421_add_claude_haiku
Revises: 20260421_agent_task_thinking
Create Date: 2026-04-21
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260421_add_claude_haiku'
down_revision: Union[str, None] = '20260421_agent_task_thinking'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add claude vendor, claude-haiku-4-5 model with billing config"""
    conn = op.get_bind()

    # 1. 添加 claude 供应商
    conn.execute(text("""
        INSERT INTO vendor (vendor_name, created_at, note)
        VALUES ('claude', NOW(), 'Anthropic Claude (via jiekou.ai)')
        ON DUPLICATE KEY UPDATE vendor_name = VALUES(vendor_name)
    """))
    logger.info("[Migration] Inserted claude vendor")

    # 2. 添加 claude-haiku-4-5 模型
    conn.execute(text("""
        INSERT INTO `model` (model_name, created_at, note, supports_tools, context_window, max_output_tokens, supports_thinking)
        VALUES ('claude-haiku-4-5', NOW(), '', 1, 20000, 64000, 0)
        ON DUPLICATE KEY UPDATE model_name = VALUES(model_name), context_window = VALUES(context_window), max_output_tokens = VALUES(max_output_tokens), supports_thinking = VALUES(supports_thinking)
    """))
    logger.info("[Migration] Inserted claude-haiku-4-5 model")

    # 3. 关联 vendor_model 计费配置
    # input $1/M, output $5/M, cache_read $0.1/M
    # 1点算力=4分钱，向下取整：
    #   input: floor(0.04 / (7.2 / 1_000_000)) = 5555
    #   output: floor(0.04 / (36 / 1_000_000)) = 1111
    #   cache: floor(0.04 / (0.72 / 1_000_000)) = 55555
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 5555, 1111, 55555, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'claude' AND m.model_name = 'claude-haiku-4-5'
    """))
    logger.info("[Migration] Added vendor_model billing: input=5555, out=1111, cache=55555, raw=NULL")


def downgrade() -> None:
    """Revert: Remove claude-haiku-4-5 model, vendor_model records, and claude vendor"""
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联
    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE model_id IN (
            SELECT id FROM `model`
            WHERE model_name = 'claude-haiku-4-5'
        )
    """))
    logger.info("[Migration] Deleted vendor_model records for claude-haiku-4-5")

    # 2. 删除 model
    conn.execute(text("""
        DELETE FROM `model` WHERE model_name = 'claude-haiku-4-5'
    """))
    logger.info("[Migration] Deleted claude-haiku-4-5 model")

    # 3. 删除 vendor
    conn.execute(text("""
        DELETE FROM vendor WHERE vendor_name = 'claude'
    """))
    logger.info("[Migration] Deleted claude vendor")
