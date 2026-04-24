"""Add qwen-plus model with tiered billing

Revision ID: 20260421_add_qwen_plus
Revises: 20260420_fix_qwen_vendor
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260421_add_qwen_plus'
down_revision: Union[str, None] = '20260420_fix_qwen_vendor'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add qwen-plus model with tiered billing configuration"""
    conn = op.get_bind()

    # 1. 添加 qwen-plus 模型到 model 表
    conn.execute(text("""
        INSERT INTO `model` (model_name, created_at, note, supports_tools, context_window)
        VALUES ('qwen-plus', NOW(), '', 1, 991000)
    """))
    logger.info("[Migration] Inserted qwen-plus model")

    # 2. 添加三档分段计费配置到 vendor_model 表
    # 0-128K档: input=50000, out=20000, cache_read=250000, raw_limit=128000
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 50000, 20000, 250000, 128000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'aliyun' AND m.model_name = 'qwen-plus'
    """))
    logger.info("[Migration] Added qwen-plus tier 1 (0-128K): input=50000, out=20000, cache_read=250000, raw_limit=128000")

    # 128K-256K档: input=16000, out=2000, cache_read=83000, raw_limit=256000
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 16000, 2000, 83000, 256000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'aliyun' AND m.model_name = 'qwen-plus'
    """))
    logger.info("[Migration] Added qwen-plus tier 2 (128K-256K): input=16000, out=2000, cache_read=83000, raw_limit=256000")

    # >256K档: input=8000, out=800, cache_read=41500, raw_limit=NULL
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 8000, 800, 41500, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'aliyun' AND m.model_name = 'qwen-plus'
    """))
    logger.info("[Migration] Added qwen-plus tier 3 (>256K): input=8000, out=800, cache_read=41500, raw_limit=NULL")


def downgrade() -> None:
    """Revert: Remove qwen-plus model and its vendor_model records"""
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联
    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE model_id IN (SELECT id FROM `model` WHERE model_name = 'qwen-plus')
    """))
    logger.info("[Migration] Deleted qwen-plus vendor_model records")

    # 2. 删除 model
    conn.execute(text("""
        DELETE FROM `model` WHERE model_name = 'qwen-plus'
    """))
    logger.info("[Migration] Deleted qwen-plus model")
