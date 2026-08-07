"""火山引擎接入 DeepSeek-V4-flash / DeepSeek-V4-pro 计费

价格来源：火山方舟控制台（元/千 tokens）
- DeepSeek-V4-flash：输入 0.0010 / 输出 0.0020 / 缓存命中 0.00020
- DeepSeek-V4-pro：  输入 0.0120 / 输出 0.0240 / 缓存命中 0.00100

换算：元/百万 = 元/千 × 1000
threshold = 0.04 × 10^6 / 单价(元/百万token)

flash: 1 / 2 / 0.2 元/百万 → 40000 / 20000 / 200000
pro:   12 / 24 / 1 元/百万 → 3333 / 1667 / 40000

Revision ID: 20260807_volc_deepseek
Revises: 20260807_vm_commission
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

revision: str = '20260807_volc_deepseek'
down_revision: Union[str, None] = '20260807_vm_commission'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 确保 volcengine 供应商存在
    conn.execute(text("""
        INSERT INTO vendor (vendor_name, created_at, note)
        SELECT 'volcengine', NOW(), '火山引擎 / 方舟 API'
        WHERE NOT EXISTS (SELECT 1 FROM vendor WHERE vendor_name = 'volcengine')
    """))

    # deepseek-v4-flash @ volcengine
    # 输入1元/百万, 输出2元/百万, 缓存命中0.2元/百万
    conn.execute(text("""
        INSERT INTO `vendor_model`
            (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold,
             cache_read_threshold, raw_token_threshold, commission_rate)
        SELECT v.id, m.id, NOW(), 40000, 20000, 200000, NULL, 0
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'volcengine' AND m.model_name = 'deepseek-v4-flash'
          AND NOT EXISTS (
              SELECT 1 FROM vendor_model vm
              WHERE vm.vendor_id = v.id AND vm.model_id = m.id
                AND (vm.raw_token_threshold IS NULL)
          )
    """))
    logger.info(
        "[Migration] volcengine/deepseek-v4-flash billing: "
        "input=40000(1元/M), out=20000(2元/M), cache=200000(0.2元/M)"
    )

    # deepseek-v4-pro @ volcengine
    # 输入12元/百万, 输出24元/百万, 缓存命中1元/百万
    conn.execute(text("""
        INSERT INTO `vendor_model`
            (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold,
             cache_read_threshold, raw_token_threshold, commission_rate)
        SELECT v.id, m.id, NOW(), 3333, 1667, 40000, NULL, 0
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'volcengine' AND m.model_name = 'deepseek-v4-pro'
          AND NOT EXISTS (
              SELECT 1 FROM vendor_model vm
              WHERE vm.vendor_id = v.id AND vm.model_id = m.id
                AND (vm.raw_token_threshold IS NULL)
          )
    """))
    logger.info(
        "[Migration] volcengine/deepseek-v4-pro billing: "
        "input=3333(12元/M), out=1667(24元/M), cache=40000(1元/M)"
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE vendor_id = (SELECT id FROM vendor WHERE vendor_name = 'volcengine')
          AND model_id IN (
              SELECT id FROM `model`
              WHERE model_name IN ('deepseek-v4-flash', 'deepseek-v4-pro')
          )
    """))
    logger.info("[Migration] Removed volcengine deepseek vendor_model rows")
