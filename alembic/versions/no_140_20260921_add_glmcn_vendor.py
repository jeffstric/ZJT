"""Add glmcn vendor (智谱 BigModel 国内站) and glm-5.3 model with billing config

Revision ID: 20260921_add_glmcn_vendor
Revises: 20260921_add_glm_5_3_flash
Create Date: 2026-09-21
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260921_add_glmcn_vendor'
down_revision: Union[str, None] = '20260921_add_glm_5_3_flash'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add glmcn vendor, glm-5.3 model and billing config

    接入方式：智谱 BigModel 国内站官方 API（open.bigmodel.cn，OpenAI 兼容端点
    /api/paas/v4），与火山方舟（volcengine）相互独立的供应商/密钥。
    GLM-5.3 为旗舰文本模型：1M 上下文 / 128K 最大输出，始终启用思考
    （reasoning_effort: low/high/max），API model ID 即 glm-5.3。
    计费档位按 BigModel 国内站刊例价折算
    （threshold = 0.04 × 10^6 / 单价(元/百万token)）：
    输入 8 元/百万 → 5000，输出 28 元/百万 → 1428，缓存命中 2.3 元/百万 → 17391。
    """
    conn = op.get_bind()

    # 1. 添加 glmcn 供应商（vendor_name 无唯一索引，用 NOT EXISTS 保证幂等）
    conn.execute(text("""
        INSERT INTO vendor (vendor_name, created_at, note)
        SELECT 'glmcn', NOW(), '智谱 BigModel 国内站（GLM-5.3 模型，OpenAI 兼容端点 open.bigmodel.cn/api/paas/v4）'
        FROM DUAL
        WHERE NOT EXISTS (SELECT 1 FROM vendor WHERE vendor_name = 'glmcn')
    """))
    logger.info("[Migration] Inserted glmcn vendor")

    # 2. 添加 glm-5.3 模型（1024K 上下文 / 128K 最大输出，支持工具调用/
    #    思考（始终开启）；纯文本输入不支持视觉；model_name 有唯一索引，幂等插入）
    conn.execute(text("""
        INSERT INTO `model` (model_name, context_window, supports_tools, max_output_tokens, supports_thinking, supports_vl, created_at, note)
        VALUES ('glm-5.3', 1024000, 1, 128000, 1, 0, NOW(), '智谱 GLM-5.3 旗舰（BigModel 国内站官方），纯文本输入，始终启用思考（reasoning_effort: low/high/max）')
        ON DUPLICATE KEY UPDATE note = VALUES(note)
    """))
    logger.info("[Migration] Inserted glm-5.3 model")

    # 3. glm-5.3 计费配置（输入 8 元/百万, 缓存命中 2.3 元/百万, 输出 28 元/百万）
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 5000, 1428, 17391, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'glmcn' AND m.model_name = 'glm-5.3'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Added glm-5.3 billing: input=5000, out=1428, cache=17391, raw_threshold=NULL")


def downgrade() -> None:
    """Revert: Remove glm-5.3 vendor_model record, model and glmcn vendor"""
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联
    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE model_id IN (SELECT id FROM `model` WHERE model_name = 'glm-5.3')
        AND vendor_id IN (SELECT id FROM vendor WHERE vendor_name = 'glmcn')
    """))
    logger.info("[Migration] Deleted vendor_model records for glm-5.3")

    # 2. 删除 model
    conn.execute(text("""
        DELETE FROM `model` WHERE model_name = 'glm-5.3'
    """))
    logger.info("[Migration] Deleted glm-5.3 model")

    # 3. 删除 glmcn 供应商（本迁移新建，可安全删除）
    conn.execute(text("""
        DELETE FROM vendor WHERE vendor_name = 'glmcn'
    """))
    logger.info("[Migration] Deleted glmcn vendor")
