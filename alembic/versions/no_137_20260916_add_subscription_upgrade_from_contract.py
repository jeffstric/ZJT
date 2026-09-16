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
    conn.execute(text("""
        ALTER TABLE subscription_orders
        ADD COLUMN IF NOT EXISTS `upgrade_from_contract_code` varchar(64) DEFAULT NULL
        COMMENT '套餐升级单：被替换的旧签约协议号(支付成功后自动解约)'
        AFTER `transaction_id`
    """))


def downgrade() -> None:
    """回滚：删除升级来源协议号字段（升级单的追溯信息将丢失，仅结构调整）"""
    conn = op.get_bind()
    conn.execute(text("""
        ALTER TABLE subscription_orders
        DROP COLUMN IF EXISTS `upgrade_from_contract_code`
    """))
