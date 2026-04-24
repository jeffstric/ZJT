"""Add gpt_image_2 implementation_power_config

Revision ID: 20260423_gpt_image_2_power
Revises: 20260423_kling_veo3_power
Create Date: 2026-04-23

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260423_gpt_image_2_power'
down_revision: Union[str, None] = '20260423_kling_veo3_power'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Insert gpt_image_2 implementation_power_config records"""
    conn = op.get_bind()

    records = [
        {
            'implementation_name': 'duomi_gpt_image_v1',
            'driver_key': 'gpt_image_2',
            'site_number': None,
            'power_config': '{"fixed": 2}',
            'sort_order': 3200.0,
        },
        {
            'implementation_name': 'gpt_image_common_site0_v1',
            'driver_key': 'gpt_image_2',
            'site_number': 0,
            'power_config': '{"fixed": 2}',
            'sort_order': 3210.0,
        },
        {
            'implementation_name': 'gpt_image_common_site1_v1',
            'driver_key': 'gpt_image_2',
            'site_number': 1,
            'power_config': '{"fixed": 2}',
            'sort_order': 3220.0,
        },
        {
            'implementation_name': 'gpt_image_common_site2_v1',
            'driver_key': 'gpt_image_2',
            'site_number': 2,
            'power_config': '{"fixed": 2}',
            'sort_order': 3230.0,
        },
        {
            'implementation_name': 'gpt_image_common_site3_v1',
            'driver_key': 'gpt_image_2',
            'site_number': 3,
            'power_config': '{"fixed": 2}',
            'sort_order': 3240.0,
        },
        {
            'implementation_name': 'gpt_image_common_site4_v1',
            'driver_key': 'gpt_image_2',
            'site_number': 4,
            'power_config': '{"fixed": 2}',
            'sort_order': 3250.0,
        },
        {
            'implementation_name': 'gpt_image_common_site5_v1',
            'driver_key': 'gpt_image_2',
            'site_number': 5,
            'power_config': '{"fixed": 2}',
            'sort_order': 3260.0,
        },
    ]

    for r in records:
        site_value = r['site_number'] if r['site_number'] is not None else 'NULL'
        result = conn.execute(text(f"""
            INSERT INTO implementation_power_config
            (implementation_name, driver_key, site_number, power_config, sort_order, enabled, updated_by)
            VALUES ('{r['implementation_name']}', '{r['driver_key']}', {site_value}, '{r['power_config']}', {r['sort_order']}, 1, 1)
            ON DUPLICATE KEY UPDATE
                power_config = VALUES(power_config),
                sort_order = VALUES(sort_order),
                enabled = VALUES(enabled)
        """))
        logger.info("[Migration] Inserted/updated implementation_power_config: %s / %s",
                    r['implementation_name'], r['driver_key'])


def downgrade() -> None:
    """Remove gpt_image_2 implementation_power_config records"""
    conn = op.get_bind()

    conn.execute(text("""
        DELETE FROM implementation_power_config
        WHERE driver_key = 'gpt_image_2'
    """))
    logger.info("[Migration] Removed gpt_image_2 implementation_power_config records")
