"""add zjt_token_enabled field

Revision ID: 20260401zjt_en
Revises: 20260401_add_zjt_token_config
Create Date: 2026-04-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '20260401zjt_en'
down_revision: Union[str, None] = '20260401_add_zjt_token_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加智剧通Token启用字段到users表"""
    conn = op.get_bind()

    # 检查列是否已存在
    result = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema=DATABASE() AND table_name='users' AND column_name='zjt_token_enabled'
    """))
    row = result.fetchone()
    count = row[0] if row else 0
    if count == 0:
        conn.execute(text("""
            ALTER TABLE `users`
            ADD COLUMN `zjt_token_enabled` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否启用智剧通Token（0-未启用，1-已启用）' AFTER `api_token`
        """))


def downgrade() -> None:
    """删除智剧通Token启用字段"""
    op.execute("ALTER TABLE `users` DROP COLUMN `zjt_token_enabled`")
