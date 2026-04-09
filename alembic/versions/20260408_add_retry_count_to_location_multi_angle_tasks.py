"""add current_angle_retry_count to location_multi_angle_tasks

Revision ID: 20260408_add_retry
Revises: 20260407_000000
Create Date: 2026-04-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260408_add_retry'
down_revision: Union[str, None] = '20260407_add_media_mapping_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('location_multi_angle_tasks', sa.Column('current_angle_retry_count', sa.Integer(), nullable=True, default=0))


def downgrade() -> None:
    op.drop_column('location_multi_angle_tasks', 'current_angle_retry_count')
