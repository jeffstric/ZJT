"""Add ZJT API vendor and associate with qwen3.5-plus/qwen3.6-plus models with tiered billing

Revision ID: 20260422_add_zjt_api
Revises: 20260421_site0_impl_power
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260422_add_zjt_api'
down_revision: Union[str, None] = '20260421_site0_impl_power'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add zjt_api vendor and associate with existing qwen3.5-plus and qwen3.6-plus models with tiered billing config"""
    conn = op.get_bind()

    # 1. 添加 zjt_api 供应商
    conn.execute(text("""
        INSERT INTO vendor (vendor_name, created_at, note)
        VALUES ('zjt_api', NOW(), 'ZJT API (Qwen 3.5/3.6 Plus)')
        ON DUPLICATE KEY UPDATE vendor_name = VALUES(vendor_name)
    """))
    logger.info("[Migration] Inserted zjt_api vendor")

    # 2. qwen3.5-plus 分段计费配置（关联到 zjt_api）
    # 分段1: raw_token_threshold=128000, input=50000, output=8334, cache_read=500000
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 50000, 8334, 500000, 128000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'zjt_api' AND m.model_name = 'qwen3.5-plus'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id AND vm.raw_token_threshold = 128000
        )
    """))
    logger.info("[Migration] Added qwen3.5-plus billing tier 1: input=50000, out=8334, cache=500000, raw_threshold=128000")

    # 分段2: raw_token_threshold=256000, input=20000, output=3334, cache_read=200000
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 20000, 3334, 200000, 256000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'zjt_api' AND m.model_name = 'qwen3.5-plus'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id AND vm.raw_token_threshold = 256000
        )
    """))
    logger.info("[Migration] Added qwen3.5-plus billing tier 2: input=20000, out=3334, cache=200000, raw_threshold=256000")

    # 分段3: raw_token_threshold=NULL (无上限), input=10000, output=1667, cache_read=100000
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 10000, 1667, 100000, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'zjt_api' AND m.model_name = 'qwen3.5-plus'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id AND vm.raw_token_threshold IS NULL
        )
    """))
    logger.info("[Migration] Added qwen3.5-plus billing tier 3 (unlimited): input=10000, out=1667, cache=100000, raw_threshold=NULL")

    # 3. qwen3.6-plus 分段计费配置（关联到 zjt_api）
    # 分段1: raw_token_threshold=256000, input=20000, output=3334, cache_read=200000
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 20000, 3334, 200000, 256000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'zjt_api' AND m.model_name = 'qwen3.6-plus'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id AND vm.raw_token_threshold = 256000
        )
    """))
    logger.info("[Migration] Added qwen3.6-plus billing tier 1: input=20000, out=3334, cache=200000, raw_threshold=256000")

    # 分段2: raw_token_threshold=NULL (无上限), input=5000, output=834, cache_read=50000
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 5000, 834, 50000, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'zjt_api' AND m.model_name = 'qwen3.6-plus'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id AND vm.raw_token_threshold IS NULL
        )
    """))
    logger.info("[Migration] Added qwen3.6-plus billing tier 2 (unlimited): input=5000, out=834, cache=50000, raw_threshold=NULL")


def downgrade() -> None:
    """Revert: Remove vendor_model records for qwen3.5-plus and qwen3.6-plus under zjt_api, and remove zjt_api vendor"""
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联（只删除 zjt_api 供应商下的记录）
    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE vendor_id = (SELECT id FROM vendor WHERE vendor_name = 'zjt_api')
        AND model_id IN (
            SELECT id FROM `model`
            WHERE model_name IN ('qwen3.5-plus', 'qwen3.6-plus')
        )
    """))
    logger.info("[Migration] Deleted vendor_model records for qwen3.5-plus and qwen3.6-plus under zjt_api")

    # 2. 删除 vendor（但不删除 model，因为 model 可能被其他 vendor 使用）
    conn.execute(text("""
        DELETE FROM vendor WHERE vendor_name = 'zjt_api'
    """))
    logger.info("[Migration] Deleted zjt_api vendor")

