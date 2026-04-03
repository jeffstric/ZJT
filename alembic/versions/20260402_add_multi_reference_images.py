"""add reference_images field to character and location

Revision ID: 20260402_multi_ref
Revises: 20260401zjt_exp
Create Date: 2026-04-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '20260402_multi_ref'
down_revision: Union[str, None] = '20260401zjt_exp'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add reference_images column to character table
    op.add_column('character', sa.Column('reference_images', sa.Text(), nullable=True, comment='Multiple reference images JSON array'))

    # Add reference_images column to location table
    op.add_column('location', sa.Column('reference_images', sa.Text(), nullable=True, comment='Multiple reference images JSON array'))

    # Migrate existing reference_image data into reference_images for character
    op.execute(text("""
        UPDATE `character`
        SET `reference_images` = JSON_ARRAY(JSON_OBJECT('label', '默认', 'url', `reference_image`))
        WHERE `reference_image` IS NOT NULL AND `reference_image` != '' AND `reference_images` IS NULL
    """))

    # Migrate existing reference_image data into reference_images for location
    op.execute(text("""
        UPDATE `location`
        SET `reference_images` = JSON_ARRAY(JSON_OBJECT('label', '默认', 'angle', 'front', 'url', `reference_image`))
        WHERE `reference_image` IS NOT NULL AND `reference_image` != '' AND `reference_images` IS NULL
    """))


def downgrade() -> None:
    op.drop_column('location', 'reference_images')
    op.drop_column('character', 'reference_images')
