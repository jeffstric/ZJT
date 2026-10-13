"""Add mimo-v2.6-flash / mimo-v2.6-pro models under existing mimo vendor

Revision ID: 20260922_add_mimo_v26_models
Revises: 20260921_link_glm_5_3_flash_glmc
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260922_add_mimo_v26_models'
down_revision: Union[str, None] = '20260921_link_glm_5_3_flash_glmc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add mimo-v2.6-flash / mimo-v2.6-pro and link them to mimo vendor

    官方规格（https://mimo.mi.com/models/zh-CN/mimo-v2.6-pro 与
    https://mimo.mi.com/models/zh-CN/mimo-v2.6-flash）：
    两款均为全模态输入（文本/图像/视频/音频），1M 上下文 / 128K 最大输出，
    支持工具调用与思考。价格与 V2.5 系列对齐：
    - mimo-v2.6-flash 对齐 mimo-v2.5：输入 1 / 输出 2 / 缓存命中 0.02 元/百万
    - mimo-v2.6-pro 对齐 mimo-v2.5-pro：输入 3 / 输出 6 / 缓存命中 0.025 元/百万
    threshold = 0.04 × 10^6 / 单价(元/百万token)
    供应商 mimo 已由 no_127 创建，本迁移只补 model + vendor_model。
    """
    conn = op.get_bind()

    # 1. mimo-v2.6-flash（1M 上下文 / 128K 最大输出，工具/思考/视觉均支持）
    conn.execute(text("""
        INSERT INTO `model` (model_name, context_window, supports_tools, max_output_tokens, supports_thinking, supports_vl, created_at, note)
        VALUES ('mimo-v2.6-flash', 1000000, 1, 128000, 1, 1, NOW(), '小米 MiMo V2.6 Flash（Token Plan），全模态输入，支持思考模式；价格对齐 mimo-v2.5')
        ON DUPLICATE KEY UPDATE note = VALUES(note)
    """))
    logger.info("[Migration] Inserted mimo-v2.6-flash model")

    # 2. mimo-v2.6-pro（官方旗舰，原生全模态，区别于纯文本的 mimo-v2.5-pro）
    conn.execute(text("""
        INSERT INTO `model` (model_name, context_window, supports_tools, max_output_tokens, supports_thinking, supports_vl, created_at, note)
        VALUES ('mimo-v2.6-pro', 1000000, 1, 128000, 1, 1, NOW(), '小米 MiMo V2.6 Pro 旗舰（Token Plan），全模态输入，支持思考模式；价格对齐 mimo-v2.5-pro')
        ON DUPLICATE KEY UPDATE note = VALUES(note)
    """))
    logger.info("[Migration] Inserted mimo-v2.6-pro model")

    # 3. mimo-v2.6-flash 计费：对齐 mimo-v2.5
    # 输入(未命中)1元/百万, 缓存命中0.02元/百万, 输出2元/百万
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 40000, 20000, 2000000, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'mimo' AND m.model_name = 'mimo-v2.6-flash'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Added mimo-v2.6-flash billing: input=40000, out=20000, cache=2000000, raw_threshold=NULL")

    # 4. mimo-v2.6-pro 计费：对齐 mimo-v2.5-pro
    # 输入(未命中)3元/百万, 缓存命中0.025元/百万, 输出6元/百万
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 13333, 6667, 1600000, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'mimo' AND m.model_name = 'mimo-v2.6-pro'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Added mimo-v2.6-pro billing: input=13333, out=6667, cache=1600000, raw_threshold=NULL")


def downgrade() -> None:
    """Revert: Remove mimo-v2.6 vendor_model records and models

    注意：mimo 供应商为存量共享（mimo-v2.5 / mimo-v2.5-pro 仍在用），不可删除。
    """
    conn = op.get_bind()

    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE vendor_id = (SELECT id FROM vendor WHERE vendor_name = 'mimo')
        AND model_id IN (
            SELECT id FROM `model`
            WHERE model_name IN ('mimo-v2.6-flash', 'mimo-v2.6-pro')
        )
    """))
    logger.info("[Migration] Deleted vendor_model records for mimo-v2.6 models")

    conn.execute(text("""
        DELETE FROM `model` WHERE model_name IN ('mimo-v2.6-flash', 'mimo-v2.6-pro')
    """))
    logger.info("[Migration] Deleted mimo-v2.6 models")
