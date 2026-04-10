"""create uncalculated_power table

Revision ID: 20260409_create_unc_power
Revises: 20260409_add_raw_input
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260409_create_unc_power'
down_revision: Union[str, None] = '20260409_add_raw_input'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'uncalculated_power',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='用户id'),
        sa.Column('accumulated_power', sa.Integer(), server_default='0', nullable=False,
                  comment='累积算力(百分位,100=1算力)'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
                  nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_charset='utf8mb4',
        mysql_comment='未扣减算力累积表',
    )
    op.create_index('idx_user_id', 'uncalculated_power', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_user_id', table_name='uncalculated_power')
    op.drop_table('uncalculated_power')
