"""Add glm-5.3-flash model (volcengine ARK) with billing config

Revision ID: 20260921_add_glm_5_3_flash
Revises: 20260917_subscription_order_firs
Create Date: 2026-09-21
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260921_add_glm_5_3_flash'
down_revision: Union[str, None] = '20260917_subscription_order_firs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add glm-5.3-flash model and volcengine billing config

    接入方式：火山方舟上架的智谱 GLM-5.3-Flash（原生多模态，始终启用思考），
    复用 volcengine 供应商（api_key / base_url 已有配置，无需新增 vendor）。
    API model ID 为 glm-5-3-flash-260828，由 volcengine 客户端 _MODEL_NAME_MAP 映射。
    规格按官方模型页：上下文 1024k / 最大输出 128k / 最大思考 128k；
    计费档位按官方按量价折算（threshold = 0.04 × 10^6 / 单价(元/百万token)）：
    输入 0.8 元/百万 → 50000，输出 2.8 元/百万 → 14285，缓存命中 0.23 元/百万 → 173913。
    """
    conn = op.get_bind()

    # 1. 添加 glm-5.3-flash 模型（1024K 上下文 / 128K 最大输出，支持工具调用/
    #    思考（始终开启）/视觉输入；model_name 有唯一索引，幂等插入）
    conn.execute(text("""
        INSERT INTO `model` (model_name, context_window, supports_tools, max_output_tokens, supports_thinking, supports_vl, created_at, note)
        VALUES ('glm-5.3-flash', 1024000, 1, 128000, 1, 1, NOW(), '智谱 GLM-5.3-Flash（火山方舟），原生多模态输入，始终启用思考（reasoning_effort: low/high/max）')
        ON DUPLICATE KEY UPDATE note = VALUES(note)
    """))
    logger.info("[Migration] Inserted glm-5.3-flash model")

    # 2. glm-5.3-flash 计费配置（volcengine 供应商已存在，仅补 vendor_model 关联）
    # 输入(未命中)0.8元/百万, 缓存命中0.23元/百万, 输出2.8元/百万
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 50000, 14285, 173913, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'volcengine' AND m.model_name = 'glm-5.3-flash'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Added glm-5.3-flash billing: input=50000, out=14285, cache=173913, raw_threshold=NULL")


def downgrade() -> None:
    """Revert: Remove glm-5.3-flash vendor_model record and model

    注意：volcengine 供应商为存量共享（doubao / deepseek 仍在用），不可删除。
    """
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联
    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE model_id IN (SELECT id FROM `model` WHERE model_name = 'glm-5.3-flash')
        AND vendor_id = (SELECT id FROM vendor WHERE vendor_name = 'volcengine')
    """))
    logger.info("[Migration] Deleted vendor_model records for glm-5.3-flash")

    # 2. 删除 model
    conn.execute(text("""
        DELETE FROM `model` WHERE model_name = 'glm-5.3-flash'
    """))
    logger.info("[Migration] Deleted glm-5.3-flash model")
