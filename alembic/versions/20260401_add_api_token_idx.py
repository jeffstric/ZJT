"""add_api_token_index

Revision ID: 20260401_add_api_token_idx
Revises: 20260401zjt_exp
Create Date: 2026-04-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


revision: str = '20260401_add_api_token_idx'
down_revision: Union[str, None] = '20260401zjt_exp'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    result = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.statistics
        WHERE table_schema=DATABASE() AND table_name='users' AND index_name='idx_api_token'
    """))
    row = result.fetchone()
    if row and row[0] == 0:
        op.create_index('idx_api_token', 'users', ['api_token'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_api_token', table_name='users')
