"""Add deepseek-v4-flash-vision-exp model (VL, same price as deepseek-v4-flash)

Revision ID: 20260830_ds_vision
Revises: 20260828_loc_plot_role
Create Date: 2026-08-30
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260830_ds_vision'
down_revision: Union[str, None] = '20260828_loc_plot_role'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add deepseek-v4-flash-vision-exp model and billing config (vendor deepseek already exists)"""
    conn = op.get_bind()

    # 1. 添加 deepseek-v4-flash-vision-exp 模型（VL 模型，支持图片理解）
    conn.execute(text("""
        INSERT INTO `model` (model_name, context_window, supports_tools, max_output_tokens, supports_thinking, supports_vl, created_at, note)
        VALUES ('deepseek-v4-flash-vision-exp', 1000000, 1, 384000, 1, 1, NOW(), 'DeepSeek V4 Flash Vision 实验版，支持图片理解，价格与 deepseek-v4-flash 相同')
        ON DUPLICATE KEY UPDATE note = VALUES(note)
    """))
    logger.info("[Migration] Inserted deepseek-v4-flash-vision-exp model")

    # 2. 计费配置：价格与 deepseek-v4-flash 一致
    # 输入1元/百万, 缓存命中0.02元/百万, 输出2元/百万
    # threshold = 0.04 × 10^6 / 单价(元/百万token)
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 40000, 20000, 2000000, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'deepseek' AND m.model_name = 'deepseek-v4-flash-vision-exp'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Added deepseek-v4-flash-vision-exp billing: input=40000, out=20000, cache=2000000, raw_threshold=NULL")


def downgrade() -> None:
    """Revert: Remove vendor_model and model for deepseek-v4-flash-vision-exp"""
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联
    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE vendor_id = (SELECT id FROM vendor WHERE vendor_name = 'deepseek')
        AND model_id IN (
            SELECT id FROM `model`
            WHERE model_name = 'deepseek-v4-flash-vision-exp'
        )
    """))
    logger.info("[Migration] Deleted vendor_model records for deepseek-v4-flash-vision-exp")

    # 2. 删除 model
    conn.execute(text("""
        DELETE FROM `model` WHERE model_name = 'deepseek-v4-flash-vision-exp'
    """))
    logger.info("[Migration] Deleted deepseek-v4-flash-vision-exp model")
