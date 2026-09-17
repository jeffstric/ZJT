"""subscription order first bonus granted

Revision ID: 20260917_subscription_order_firs
Revises: 20260916_add_subscription_upgrad
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260917_subscription_order_firs'
down_revision: Union[str, None] = '20260916_add_subscription_upgrad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """首订加赠改为签约成功后发放：subscription_orders 增加 first_bonus_granted 标记列。

    业务规则：first_period_bonus 仅在「签约成功」后发放（用户只付款但签约未生效不发），
    且仅限用户首份成功签约的合约的首期订单。该列标记加赠是否已发放（幂等 + 审计）。
    """
    conn = op.get_bind()
    # MySQL 不支持 ADD COLUMN IF NOT EXISTS（MariaDB 语法），用 information_schema 预检保证幂等
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'subscription_orders'
          AND COLUMN_NAME = 'first_bonus_granted'
    """)).scalar()
    if exists:
        logger.info("[Migration] subscription_orders.first_bonus_granted already exists, skip")
        return
    conn.execute(text("""
        ALTER TABLE subscription_orders
        ADD COLUMN `first_bonus_granted` tinyint(1) NOT NULL DEFAULT 0
        COMMENT '首订加赠是否已发放(1=已发放；仅签约成功后发放，幂等防重)'
        AFTER `upgrade_from_contract_code`
    """))
    logger.info("[Migration] added subscription_orders.first_bonus_granted")


def downgrade() -> None:
    """回滚：删除首订加赠标记列（加赠发放记录将丢失，仅结构调整）"""
    conn = op.get_bind()
    # MySQL 不支持 DROP COLUMN IF EXISTS，同样用 information_schema 预检
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'subscription_orders'
          AND COLUMN_NAME = 'first_bonus_granted'
    """)).scalar()
    if not exists:
        return
    conn.execute(text("""
        ALTER TABLE subscription_orders
        DROP COLUMN `first_bonus_granted`
    """))
    logger.info("[Migration] dropped subscription_orders.first_bonus_granted")
