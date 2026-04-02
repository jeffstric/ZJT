"""add_api_token_to_users

Revision ID: add_api_token_to_users
Revises:
Create Date: 2026-04-01

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260401_add_api_token_to_users'
down_revision = '20260329_rename_pro_model'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('api_token', sa.String(64), nullable=True, comment='用户API Token（智剧通接口授权）'))
    op.create_index('idx_api_token', 'users', ['api_token'], unique=True)


def downgrade():
    op.drop_index('idx_api_token', table_name='users')
    op.drop_column('users', 'api_token')
