"""add users channel level

Revision ID: 20260916_add_users_channel_level
Revises: 20260911_wx_papay_subscription
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260916_add_users_channel_level'
down_revision: Union[str, None] = '20260911_wx_papay_subscription'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """用户渠道推广等级：0-未开通 1-推广链接(算力奖励) 2-渠道佣金(现金)"""
    conn = op.get_bind()
    conn.execute(text("""
        ALTER TABLE users
        ADD COLUMN channel_level TINYINT NOT NULL DEFAULT 0
        COMMENT '渠道推广等级 0-未开通 1-推广链接(算力奖励) 2-渠道佣金(现金)'
        AFTER commission_rate
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("ALTER TABLE users DROP COLUMN channel_level"))
def downgrade() -> None:
    """TODO: 回滚操作；数据修复类迁移可留空（pass），避免误删数据"""
    pass
