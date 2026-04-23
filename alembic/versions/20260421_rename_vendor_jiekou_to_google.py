"""Rename vendor 'jiekou' to 'google' in vendor table

Revision ID: 20260421_rename_jiekou_google
Revises: 20260421_site0_aggregator
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260421_rename_jiekou_google'
down_revision: Union[str, None] = '20260421_site0_aggregator'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename vendor_name from 'jiekou' to 'google'"""
    conn = op.get_bind()

    result = conn.execute(text("""
        UPDATE vendor SET vendor_name = 'google' WHERE vendor_name = 'jiekou'
    """))
    logger.info("[Migration] Renamed %s vendor(s) from 'jiekou' to 'google'", result.rowcount)


def downgrade() -> None:
    """Revert vendor_name from 'google' back to 'jiekou'"""
    conn = op.get_bind()

    result = conn.execute(text("""
        UPDATE vendor SET vendor_name = 'jiekou' WHERE vendor_name = 'google'
    """))
    logger.info("[Migration] Reverted %s vendor(s) from 'google' to 'jiekou'", result.rowcount)
