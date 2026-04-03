"""add zjt_token_expire_at field

Revision ID: 20260401zjt_exp
Revises: 20260401zjt_en
Create Date: 2026-04-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '20260401zjt_exp'
down_revision: Union[str, None] = '20260401zjt_en'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加智剧通Token过期时间字段到users表"""
    conn = op.get_bind()

    # 检查列是否已存在
    result = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema=DATABASE() AND table_name='users' AND column_name='zjt_token_expire_at'
    """))
    row = result.fetchone()
    count = row[0] if row else 0
    if count == 0:
        conn.execute(text("""
            ALTER TABLE `users`
            ADD COLUMN `zjt_token_expire_at` DATETIME DEFAULT NULL COMMENT '智剧通Token过期时间' AFTER `zjt_token_enabled`
        """))


def downgrade() -> None:
    """删除智剧通Token过期时间字段"""
    op.execute("ALTER TABLE `users` DROP COLUMN `zjt_token_expire_at`")
