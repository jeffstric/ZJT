"""add subscription upgrade from contract

Revision ID: 20260916_add_subscription_upgrad
Revises: 20260916_add_users_channel_level
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260916_add_subscription_upgrad'
down_revision: Union[str, None] = '20260916_add_users_channel_level'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """订阅套餐升级：subscription_orders 增加 upgrade_from_contract_code（记录被替换的旧签约）"""
    conn = op.get_bind()
    # MySQL 不支持 ADD COLUMN IF NOT EXISTS（MariaDB 语法），用 information_schema 预检保证幂等
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'subscription_orders'
          AND COLUMN_NAME = 'upgrade_from_contract_code'
    """)).scalar()
    if exists:
        logger.info("[Migration] subscription_orders.upgrade_from_contract_code already exists, skip")
        return
    conn.execute(text("""
        ALTER TABLE subscription_orders
        ADD COLUMN `upgrade_from_contract_code` varchar(64) DEFAULT NULL
        COMMENT '套餐升级单：被替换的旧签约协议号(支付成功后自动解约)'
        AFTER `transaction_id`
    """))
    logger.info("[Migration] added subscription_orders.upgrade_from_contract_code")


def downgrade() -> None:
    """回滚：删除升级来源协议号字段（升级单的追溯信息将丢失，仅结构调整）"""
    conn = op.get_bind()
    # MySQL 不支持 DROP COLUMN IF EXISTS，同样用 information_schema 预检
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'subscription_orders'
          AND COLUMN_NAME = 'upgrade_from_contract_code'
    """)).scalar()
    if not exists:
        return
    conn.execute(text("""
        ALTER TABLE subscription_orders
        DROP COLUMN `upgrade_from_contract_code`
    """))
    logger.info("[Migration] dropped subscription_orders.upgrade_from_contract_code")
