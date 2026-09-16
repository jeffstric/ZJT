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
down_revision: Union[str, Sequence[str], None] = '20260911_wx_papay_subscription'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """用户渠道推广等级：0-未开通佣金 1-推广链接(算力) 2-渠道佣金(现金)"""
    conn = op.get_bind()
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND COLUMN_NAME = 'channel_level'
    """)).scalar()
    if exists:
        logger.info("[Migration] users.channel_level already exists, skip")
        return
    conn.execute(text("""
        ALTER TABLE users
        ADD COLUMN channel_level TINYINT NOT NULL DEFAULT 0
        COMMENT '渠道推广等级 0-未开通佣金 1-推广链接(算力) 2-渠道佣金(现金)'
        AFTER commission_rate
    """))
    logger.info("[Migration] added users.channel_level")


def downgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'users'
          AND COLUMN_NAME = 'channel_level'
    """)).scalar()
    if not exists:
        return
    conn.execute(text("ALTER TABLE users DROP COLUMN channel_level"))
    logger.info("[Migration] dropped users.channel_level")
