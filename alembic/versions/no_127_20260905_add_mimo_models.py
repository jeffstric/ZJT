"""Add Xiaomi MiMo vendor (Token Plan) and mimo-v2.5/mimo-v2.5-pro models with billing config

Revision ID: 20260905_add_mimo_models
Revises: 20260904_add_vendor_id_to_chat_s
Create Date: 2026-09-05
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260905_add_mimo_models'
down_revision: Union[str, None] = '20260904_add_vendor_id_to_chat_s'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add mimo vendor, mimo-v2.5 and mimo-v2.5-pro models, and billing config

    接入方式：小米 MiMo Token Plan 套餐（包月 credits），
    OpenAI 兼容端点 https://token-plan-cn.xiaomimimo.com/v1
    计费档位按官方按量价折算（threshold = 0.04 × 10^6 / 单价(元/百万token)）
    """
    conn = op.get_bind()

    # 1. 添加 mimo 供应商（vendor_name 无唯一索引，用 NOT EXISTS 保证幂等）
    conn.execute(text("""
        INSERT INTO vendor (vendor_name, created_at, note)
        SELECT 'mimo', NOW(), '小米 MiMo 开放平台（Token Plan 套餐，OpenAI 兼容端点 token-plan-cn.xiaomimimo.com/v1）'
        FROM DUAL
        WHERE NOT EXISTS (SELECT 1 FROM vendor WHERE vendor_name = 'mimo')
    """))
    logger.info("[Migration] Inserted mimo vendor (if not exists)")

    # 2. 添加 mimo-v2.5 模型（1M 上下文 / 128K 最大输出，支持工具调用/思考/视觉）
    conn.execute(text("""
        INSERT INTO `model` (model_name, context_window, supports_tools, max_output_tokens, supports_thinking, supports_vl, created_at, note)
        VALUES ('mimo-v2.5', 1000000, 1, 128000, 1, 1, NOW(), '小米 MiMo V2.5（Token Plan），全模态输入，支持思考模式')
        ON DUPLICATE KEY UPDATE note = VALUES(note)
    """))
    logger.info("[Migration] Inserted mimo-v2.5 model")

    # 3. 添加 mimo-v2.5-pro 模型
    conn.execute(text("""
        INSERT INTO `model` (model_name, context_window, supports_tools, max_output_tokens, supports_thinking, supports_vl, created_at, note)
        VALUES ('mimo-v2.5-pro', 1000000, 1, 128000, 1, 1, NOW(), '小米 MiMo V2.5 Pro 旗舰（Token Plan），全模态输入，支持思考模式')
        ON DUPLICATE KEY UPDATE note = VALUES(note)
    """))
    logger.info("[Migration] Inserted mimo-v2.5-pro model")

    # 4. mimo-v2.5 计费配置
    # 输入(未命中)1元/百万, 缓存命中0.02元/百万, 输出2元/百万
    # threshold = 0.04 × 10^6 / 单价(元/百万token)
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 40000, 20000, 2000000, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'mimo' AND m.model_name = 'mimo-v2.5'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Added mimo-v2.5 billing: input=40000, out=20000, cache=2000000, raw_threshold=NULL")

    # 5. mimo-v2.5-pro 计费配置
    # 输入(未命中)3元/百万, 缓存命中0.025元/百万, 输出6元/百万
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 13333, 6667, 1600000, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'mimo' AND m.model_name = 'mimo-v2.5-pro'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Added mimo-v2.5-pro billing: input=13333, out=6667, cache=1600000, raw_threshold=NULL")


def downgrade() -> None:
    """Revert: Remove vendor_model records, models, and vendor for MiMo"""
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联
    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE vendor_id = (SELECT id FROM vendor WHERE vendor_name = 'mimo')
        AND model_id IN (
            SELECT id FROM `model`
            WHERE model_name IN ('mimo-v2.5', 'mimo-v2.5-pro')
        )
    """))
    logger.info("[Migration] Deleted vendor_model records for mimo models")

    # 2. 删除 model
    conn.execute(text("""
        DELETE FROM `model` WHERE model_name IN ('mimo-v2.5', 'mimo-v2.5-pro')
    """))
    logger.info("[Migration] Deleted mimo models")

    # 3. 删除 vendor
    conn.execute(text("""
        DELETE FROM vendor WHERE vendor_name = 'mimo'
    """))
    logger.info("[Migration] Deleted mimo vendor")
