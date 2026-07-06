"""Add composition_preference to storyboard

Revision ID: 20260624_storyboard_comp
Revises: 20260622_storyboard
Create Date: 2026-06-24
"""
from typing import Sequence, Union

from alembic import op


revision: str = '20260624_storyboard_comp'
down_revision: Union[str, None] = '20260622_storyboard'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add storyboard composition preference inherited from world."""
    op.execute("""
        ALTER TABLE `storyboard`
        ADD COLUMN `composition_preference` VARCHAR(500) DEFAULT NULL COMMENT '构图倾向，来自 world.composition_preference'
        AFTER `workflow_ratio`
    """)


def downgrade() -> None:
    """Remove storyboard composition preference."""
    op.execute("ALTER TABLE `storyboard` DROP COLUMN `composition_preference`")
