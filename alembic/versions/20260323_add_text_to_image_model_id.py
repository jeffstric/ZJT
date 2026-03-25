"""add_text_to_image_model_id_to_chat_sessions

Revision ID: 20260323_001
Revises: 20260322_chat_sessions
Create Date: 2026-03-23 22:30:00.000000+08:00

Add text_to_image_model_id field to chat_sessions table for storing text-to-image model configuration
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260323_001'
down_revision: Union[str, None] = '20260322_chat_sessions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add text_to_image_model_id field to chat_sessions table"""
    op.execute("""
        ALTER TABLE `chat_sessions`
        ADD COLUMN `text_to_image_model_id` INT DEFAULT NULL COMMENT 'Text-to-image model task ID'
        AFTER `model_id`
    """)
    print("[Migration] Added text_to_image_model_id field to chat_sessions table")


def downgrade() -> None:
    """Remove text_to_image_model_id field from chat_sessions table"""
    op.execute("""
        ALTER TABLE `chat_sessions`
        DROP COLUMN `text_to_image_model_id`
    """)
    print("[Migration] Removed text_to_image_model_id field from chat_sessions table")
