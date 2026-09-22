"""Link glm-5.3-flash model to glmcn vendor with billing config

Revision ID: 20260921_link_glm_5_3_flash_glmc
Revises: 20260921_add_glmcn_vendor
Create Date: 2026-09-21
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260921_link_glm_5_3_flash_glmc'
down_revision: Union[str, None] = '20260921_add_glmcn_vendor'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Link existing glm-5.3-flash model to glmcn vendor

    glm-5.3-flash 在智谱 BigModel 国内站官方 API 同样提供（model ID 一致），
    官方定价与火山方舟相同：输入 0.8 / 输出 2.8 / 缓存命中 0.23 元/百万
    （threshold = 0.04 × 10^6 / 单价 → 50000 / 14285 / 173913）。
    model 记录由 no_139 创建、两个供应商共用；本条迁移仅：
    1. 把 model.note 更新为供应商中立的描述（原 note 只写「火山方舟」）；
    2. 补 glmcn 的 vendor_model 关联（按 vendor_id 精确路由到智谱密钥）。
    """
    conn = op.get_bind()

    # 1. model.note 去供应商化（model_name 唯一索引，幂等）
    conn.execute(text("""
        INSERT INTO `model` (model_name, context_window, supports_tools, max_output_tokens, supports_thinking, supports_vl, created_at, note)
        VALUES ('glm-5.3-flash', 1024000, 1, 128000, 1, 1, NOW(), '智谱 GLM-5.3-Flash，原生多模态输入，始终启用思考（reasoning_effort: low/high/max）；支持火山引擎 / 智谱 BigModel 双供应商')
        ON DUPLICATE KEY UPDATE note = VALUES(note)
    """))
    logger.info("[Migration] Updated glm-5.3-flash model note (vendor-neutral)")

    # 2. glmcn 供应商关联（幂等：NOT EXISTS 守卫）
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 50000, 14285, 173913, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'glmcn' AND m.model_name = 'glm-5.3-flash'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info("[Migration] Linked glm-5.3-flash to glmcn: input=50000, out=14285, cache=173913, raw_threshold=NULL")


def downgrade() -> None:
    """Revert: Remove only the glmcn vendor_model link

    注意：glm-5.3-flash 的 model 记录与 volcengine 关联由 no_139 管理，
    本迁移只删除 glmcn 关联，不动 model / volcengine vendor。
    """
    conn = op.get_bind()

    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE model_id IN (SELECT id FROM `model` WHERE model_name = 'glm-5.3-flash')
        AND vendor_id IN (SELECT id FROM vendor WHERE vendor_name = 'glmcn')
    """))
    logger.info("[Migration] Deleted glmcn vendor_model link for glm-5.3-flash")
