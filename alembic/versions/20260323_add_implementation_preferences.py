"""add implementation_preferences to users

Revision ID: 20260323_add_impl_prefs
Revises: 20260323_change_impl_power_unique_key
Create Date: 2026-03-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260323_add_impl_prefs'
down_revision = '20260323_impl_power_composite'
branch_labels = None
depends_on = None


def upgrade():
    """添加 implementation_preferences 和 active_preference_group 列到 users 表"""
    # 检查列是否已存在
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('users')]

    if 'implementation_preferences' not in columns:
        op.add_column('users',
            sa.Column('implementation_preferences', sa.JSON(), nullable=True, comment='用户实现方偏好配置')
        )
        print("Added column: implementation_preferences")

    if 'active_preference_group' not in columns:
        op.add_column('users',
            sa.Column('active_preference_group', sa.Integer(), nullable=True, default=1, comment='当前激活的偏好组')
        )
        print("Added column: active_preference_group")


def downgrade():
    """移除 implementation_preferences 和 active_preference_group 列"""
    op.drop_column('users', 'implementation_preferences')
    op.drop_column('users', 'active_preference_group')
