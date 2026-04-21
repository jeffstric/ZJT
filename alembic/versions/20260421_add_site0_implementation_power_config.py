"""Add site_0 implementation_power_config for Gemini and VEO3

Revision ID: 20260421_site0_impl_power
Revises: 20260421_rename_jiekou_google
Create Date: 2026-04-21

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260421_site0_impl_power'
down_revision: Union[str, None] = '20260421_rename_jiekou_google'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Insert site_0 implementation_power_config records for Gemini and VEO3"""
    conn = op.get_bind()

    records = [
        # Gemini image_edit
        {
            'implementation_name': 'gemini_image_preview_site0_v1',
            'driver_key': 'gemini_image_edit',
            'site_number': 0,
            'power_config': '{"fixed": 2}',
            'sort_order': 10500.0,
        },
        # Gemini image_edit_pro
        {
            'implementation_name': 'gemini_image_preview_site0_v1',
            'driver_key': 'gemini_image_edit_pro',
            'site_number': 0,
            'power_config': '{"fixed": 2}',
            'sort_order': 10500.0,
        },
        # Gemini 3.1 flash image_edit
        {
            'implementation_name': 'gemini_image_preview_site0_v1',
            'driver_key': 'gemini_3_1_flash_image_edit',
            'site_number': 0,
            'power_config': '{"fixed": 3}',
            'sort_order': 10500.0,
        },
        # VEO3 image_to_video
        {
            'implementation_name': 'veo3_common_site0_v1',
            'driver_key': 'veo3_image_to_video',
            'site_number': 0,
            'power_config': '{"8": 6}',
            'sort_order': 4010.0,
        },
    ]

    for r in records:
        result = conn.execute(text("""
            INSERT INTO implementation_power_config
            (implementation_name, driver_key, site_number, power_config, sort_order, enabled, updated_by)
            VALUES (:implementation_name, :driver_key, :site_number, :power_config, :sort_order, 1, 1)
            ON DUPLICATE KEY UPDATE
                power_config = VALUES(power_config),
                sort_order = VALUES(sort_order)
        """), r)
        logger.info("[Migration] Inserted/updated implementation_power_config: %s / %s",
                    r['implementation_name'], r['driver_key'])


def downgrade() -> None:
    """Remove site_0 implementation_power_config records"""
    conn = op.get_bind()

    conn.execute(text("""
        DELETE FROM implementation_power_config
        WHERE implementation_name = 'gemini_image_preview_site0_v1'
           OR implementation_name = 'veo3_common_site0_v1'
    """))
    logger.info("[Migration] Removed site_0 implementation_power_config records")
