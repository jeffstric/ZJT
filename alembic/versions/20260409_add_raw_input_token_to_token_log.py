"""add raw_input_token to token_log

Revision ID: 20260409_add_raw_input
Revises: 20260408_add_retry
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260409_add_raw_input'
down_revision: Union[str, None] = '20260408_add_retry'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('token_log', sa.Column('raw_input_token', sa.Integer(), nullable=True, comment='API原始输入token'))


def downgrade() -> None:
    op.drop_column('token_log', 'raw_input_token')
