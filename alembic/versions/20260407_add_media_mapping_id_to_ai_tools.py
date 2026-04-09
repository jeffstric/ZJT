"""add media_mapping_id to ai_tools

Revision ID: 20260407_add_media_mapping_id
Revises: 20260404_create_media
Create Date: 2026-04-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260407_add_media_mapping_id'
down_revision: Union[str, None] = '20260404_create_media'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ai_tools', sa.Column('media_mapping_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_ai_tools_media_mapping_id', 'ai_tools', 'media_file_mapping', ['media_mapping_id'], ['id'])
    op.create_index('idx_media_mapping_id', 'ai_tools', ['media_mapping_id'])


def downgrade() -> None:
    op.drop_index('idx_media_mapping_id', table_name='ai_tools')
    op.drop_constraint('fk_ai_tools_media_mapping_id', table_name='ai_tools', type_='foreignkey')
    op.drop_column('ai_tools', 'media_mapping_id')
