"""
添加 implementation 字段到 ai_tools 表

用于记录任务实际使用的服务商实现

Revision ID: 20260326_impl_field
Revises: 20260323_add_impl_prefs
Create Date: 2026-03-26 10:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260326_impl_field'
down_revision = '20260323_add_impl_prefs'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE `ai_tools`
        ADD COLUMN `implementation` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '服务商实现ID，参考 DriverImplementationId'
    """)

def downgrade():
    op.execute("""
        ALTER TABLE `ai_tools`
        DROP COLUMN `implementation`
    """)
