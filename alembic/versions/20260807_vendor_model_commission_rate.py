"""vendor_model 增加 commission_rate 抽成比例

Revision ID: 20260807_vm_commission
Revises: 20260801_slow_query_idx
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

revision: str = '20260807_vm_commission'
down_revision: Union[str, None] = '20260801_slow_query_idx'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # 幂等：仅当列不存在时添加
    rows = conn.execute(text("""
        SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'vendor_model'
          AND COLUMN_NAME = 'commission_rate'
    """)).fetchone()
    cnt = rows[0] if rows and not hasattr(rows, 'keys') else (rows['cnt'] if rows else 0)
    if int(cnt or 0) == 0:
        conn.execute(text("""
            ALTER TABLE `vendor_model`
            ADD COLUMN `commission_rate` DECIMAL(5,4) NOT NULL DEFAULT 0
            COMMENT '抽成比例 0~1，计费时算力乘以 (1+commission_rate)'
            AFTER `raw_token_threshold`
        """))
        logger.info("[Migration] Added vendor_model.commission_rate")
    else:
        logger.info("[Migration] vendor_model.commission_rate already exists, skip")


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(text("""
        SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'vendor_model'
          AND COLUMN_NAME = 'commission_rate'
    """)).fetchone()
    cnt = rows[0] if rows and not hasattr(rows, 'keys') else (rows['cnt'] if rows else 0)
    if int(cnt or 0) > 0:
        conn.execute(text("ALTER TABLE `vendor_model` DROP COLUMN `commission_rate`"))
        logger.info("[Migration] Dropped vendor_model.commission_rate")
