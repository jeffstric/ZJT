"""Add Agnes vendor and agnes-2.5-flash / agnes-2.5-pro chat models

价格来源：Agnes 官方文档标准价（美元/百万 tokens），按 7.2 汇率换算为元/百万。
Flash 文档促销价当前为 $0，计费按标准价写入以便促销结束后不至于算力过松。

agnes-2.5-flash 标准价：输入 $0.03 / 输出 $0.15
  → 约 0.216 / 1.08 元/百万
  → threshold = 0.04e6 / 单价 → 185185 / 37037 / NULL

agnes-2.5-pro 标准价：输入 $0.45 / 输出 $0.90 / 缓存读 $0.0038
  → 约 3.24 / 6.48 / 0.02736 元/百万
  → threshold → 12346 / 6173 / 1461988

Revision ID: 20260810_add_agnes
Revises: 20260807_volc_deepseek
Create Date: 2026-08-10
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

revision: str = '20260810_add_agnes'
down_revision: Union[str, None] = '20260807_volc_deepseek'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add agnes vendor, chat models, and billing config"""
    conn = op.get_bind()

    # 1. 添加 agnes 供应商
    conn.execute(text("""
        INSERT INTO vendor (vendor_name, created_at, note)
        SELECT 'agnes', NOW(), 'Agnes AI Chat Completions API'
        WHERE NOT EXISTS (SELECT 1 FROM vendor WHERE vendor_name = 'agnes')
    """))
    logger.info("[Migration] Inserted agnes vendor")

    # 2. agnes-2.5-flash
    conn.execute(text("""
        INSERT INTO `model` (
            model_name, context_window, supports_tools, max_output_tokens,
            supports_thinking, supports_vl, created_at, note
        )
        SELECT 'agnes-2.5-flash', 524288, 1, 65536, 1, 1, NOW(),
               'Agnes 2.5 Flash 对话模型，支持工具调用/思考/图像URL'
        WHERE NOT EXISTS (SELECT 1 FROM `model` WHERE model_name = 'agnes-2.5-flash')
    """))
    logger.info("[Migration] Inserted agnes-2.5-flash model")

    # 3. agnes-2.5-pro
    conn.execute(text("""
        INSERT INTO `model` (
            model_name, context_window, supports_tools, max_output_tokens,
            supports_thinking, supports_vl, created_at, note
        )
        SELECT 'agnes-2.5-pro', 1048576, 1, 65536, 1, 1, NOW(),
               'Agnes 2.5 Pro 对话/推理模型，支持工具调用/思考/图像URL'
        WHERE NOT EXISTS (SELECT 1 FROM `model` WHERE model_name = 'agnes-2.5-pro')
    """))
    logger.info("[Migration] Inserted agnes-2.5-pro model")

    # 4. flash 计费
    conn.execute(text("""
        INSERT INTO `vendor_model` (
            vendor_id, model_id, created_at,
            input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold
        )
        SELECT v.id, m.id, NOW(), 185185, 37037, NULL, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'agnes' AND m.model_name = 'agnes-2.5-flash'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Added agnes-2.5-flash billing: input=185185, out=37037")

    # 5. pro 计费
    conn.execute(text("""
        INSERT INTO `vendor_model` (
            vendor_id, model_id, created_at,
            input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold
        )
        SELECT v.id, m.id, NOW(), 12346, 6173, 1461988, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'agnes' AND m.model_name = 'agnes-2.5-pro'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Added agnes-2.5-pro billing: input=12346, out=6173, cache=1461988")


def downgrade() -> None:
    """Revert: Remove vendor_model, models, and vendor for Agnes"""
    conn = op.get_bind()

    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE vendor_id = (SELECT id FROM vendor WHERE vendor_name = 'agnes')
        AND model_id IN (
            SELECT id FROM `model`
            WHERE model_name IN ('agnes-2.5-flash', 'agnes-2.5-pro')
        )
    """))
    logger.info("[Migration] Deleted vendor_model records for agnes models")

    conn.execute(text("""
        DELETE FROM `model` WHERE model_name IN ('agnes-2.5-flash', 'agnes-2.5-pro')
    """))
    logger.info("[Migration] Deleted agnes models")

    conn.execute(text("""
        DELETE FROM vendor WHERE vendor_name = 'agnes'
    """))
    logger.info("[Migration] Deleted agnes vendor")
