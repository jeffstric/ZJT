"""Add volcengine vendor and Doubao Seed 2.0 models with tiered billing

新增火山引擎供应商及 Doubao Seed 2.0 模型（pro/lite），各配置三档分段计费。

Revision ID: 20260420_add_volcengine_doubao
Revises: 20260421_add_max_output_tokens
Create Date: 2026-04-20
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260420_add_volcengine_doubao'
down_revision: Union[str, None] = '20260421_add_max_output_tokens'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add volcengine vendor, Doubao Seed 2.0 pro/lite models with tiered billing"""
    conn = op.get_bind()

    # 1. 添加 volcengine 供应商
    conn.execute(text("""
        INSERT INTO vendor (vendor_name, created_at, note)
        VALUES ('volcengine', NOW(), '火山引擎（字节跳动）')
        ON DUPLICATE KEY UPDATE vendor_name = VALUES(vendor_name)
    """))
    logger.info("[Migration] Inserted volcengine vendor")

    # 2. 添加 doubao-seed-2-0-pro 模型
    conn.execute(text("""
        INSERT INTO `model` (model_name, created_at, note, supports_tools, context_window, max_output_tokens)
        VALUES ('doubao-seed-2-0-pro', NOW(), '', 1, 256000, 128000)
        ON DUPLICATE KEY UPDATE model_name = VALUES(model_name), context_window = VALUES(context_window), max_output_tokens = VALUES(max_output_tokens)
    """))
    logger.info("[Migration] Inserted doubao-seed-2-0-pro model")

    # 3. 添加 doubao-seed-2-0-lite 模型
    conn.execute(text("""
        INSERT INTO `model` (model_name, created_at, note, supports_tools, context_window, max_output_tokens)
        VALUES ('doubao-seed-2-0-lite', NOW(), '', 1, 256000, 128000)
        ON DUPLICATE KEY UPDATE model_name = VALUES(model_name), context_window = VALUES(context_window), max_output_tokens = VALUES(max_output_tokens)
    """))
    logger.info("[Migration] Inserted doubao-seed-2-0-lite model")

    # 4. doubao-seed-2-0-pro 三档分段计费
    # 档位1: ≤32K — input=3.2, out=16, cache=0.64
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 12500, 2500, 62500, 32000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'volcengine' AND m.model_name = 'doubao-seed-2-0-pro'
    """))
    logger.info("[Migration] Added pro tier 1 (<=32K): input=12500, out=2500, cache=62500, raw=32000")

    # 档位2: 32K~128K — input=4.8, out=24, cache=0.96
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 8333, 1666, 41666, 128000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'volcengine' AND m.model_name = 'doubao-seed-2-0-pro'
    """))
    logger.info("[Migration] Added pro tier 2 (32K~128K): input=8333, out=1666, cache=41666, raw=128000")

    # 档位3: 128K~256K — input=9.6, out=48, cache=1.92
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 4166, 833, 20833, 256000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'volcengine' AND m.model_name = 'doubao-seed-2-0-pro'
    """))
    logger.info("[Migration] Added pro tier 3 (128K~256K): input=4166, out=833, cache=20833, raw=256000")

    # 5. doubao-seed-2-0-lite 三档分段计费
    # 档位1: ≤32K — input=0.6, out=3.6, cache=0.12
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 66666, 11111, 333333, 32000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'volcengine' AND m.model_name = 'doubao-seed-2-0-lite'
    """))
    logger.info("[Migration] Added lite tier 1 (<=32K): input=66666, out=11111, cache=333333, raw=32000")

    # 档位2: 32K~128K — input=0.9, out=5.4, cache=0.18
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 44444, 7407, 222222, 128000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'volcengine' AND m.model_name = 'doubao-seed-2-0-lite'
    """))
    logger.info("[Migration] Added lite tier 2 (32K~128K): input=44444, out=7407, cache=222222, raw=128000")

    # 档位3: 128K~256K — input=1.8, out=10.8, cache=0.36
    conn.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, NOW(), 22222, 3703, 111111, 256000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'volcengine' AND m.model_name = 'doubao-seed-2-0-lite'
    """))
    logger.info("[Migration] Added lite tier 3 (128K~256K): input=22222, out=3703, cache=111111, raw=256000")


def downgrade() -> None:
    """Revert: Remove Doubao models, vendor_model records, and volcengine vendor"""
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联
    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE model_id IN (
            SELECT id FROM `model`
            WHERE model_name IN ('doubao-seed-2-0-pro', 'doubao-seed-2-0-lite')
        )
    """))
    logger.info("[Migration] Deleted vendor_model records for Doubao models")

    # 2. 删除 models
    conn.execute(text("""
        DELETE FROM `model` WHERE model_name IN ('doubao-seed-2-0-pro', 'doubao-seed-2-0-lite')
    """))
    logger.info("[Migration] Deleted Doubao models")

    # 3. 删除 vendor
    conn.execute(text("""
        DELETE FROM vendor WHERE vendor_name = 'volcengine'
    """))
    logger.info("[Migration] Deleted volcengine vendor")
