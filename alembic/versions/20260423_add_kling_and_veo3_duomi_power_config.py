"""Add kling and veo3_duomi_v1 implementation_power_config

Revision ID: 20260423_kling_veo3_power
Revises: 20260422_add_zjt_api
Create Date: 2026-04-23

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260423_kling_veo3_power'
down_revision: Union[str, None] = '20260422_add_zjt_api'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Insert kling and veo3_duomi_v1 implementation_power_config records"""
    conn = op.get_bind()

    records = [
        # Kling implementations
        {
            'implementation_name': 'kling_duomi_v1',
            'driver_key': 'kling_image_to_video',
            'site_number': None,
            'power_config': '{"5": 38, "10": 70}',
            'sort_order': 2010.0,
        },
        {
            'implementation_name': 'kling_common_site0_v1',
            'driver_key': 'kling_image_to_video',
            'site_number': 0,
            'power_config': '{"5": 38, "10": 70}',
            'sort_order': 2000.0,
        },
        {
            'implementation_name': 'kling_common_site1_v1',
            'driver_key': 'kling_image_to_video',
            'site_number': 1,
            'power_config': '{"5": 38, "10": 70}',
            'sort_order': 2020.0,
        },
        {
            'implementation_name': 'kling_common_site2_v1',
            'driver_key': 'kling_image_to_video',
            'site_number': 2,
            'power_config': '{"5": 38, "10": 70}',
            'sort_order': 2030.0,
        },
        {
            'implementation_name': 'kling_common_site3_v1',
            'driver_key': 'kling_image_to_video',
            'site_number': 3,
            'power_config': '{"5": 38, "10": 70}',
            'sort_order': 2040.0,
        },
        {
            'implementation_name': 'kling_common_site4_v1',
            'driver_key': 'kling_image_to_video',
            'site_number': 4,
            'power_config': '{"5": 38, "10": 70}',
            'sort_order': 2050.0,
        },
        {
            'implementation_name': 'kling_common_site5_v1',
            'driver_key': 'kling_image_to_video',
            'site_number': 5,
            'power_config': '{"5": 38, "10": 70}',
            'sort_order': 2060.0,
        },
        # VEO3 duomi implementation
        {
            'implementation_name': 'veo3_duomi_v1',
            'driver_key': 'veo3_image_to_video',
            'site_number': None,
            'power_config': '{"fixed": 6}',
            'sort_order': 4000.0,
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
    """Remove kling and veo3_duomi_v1 implementation_power_config records"""
    conn = op.get_bind()

    implementations_to_remove = [
        'kling_duomi_v1',
        'kling_common_site0_v1',
        'kling_common_site1_v1',
        'kling_common_site2_v1',
        'kling_common_site3_v1',
        'kling_common_site4_v1',
        'kling_common_site5_v1',
        'veo3_duomi_v1',
    ]

    for impl_name in implementations_to_remove:
        conn.execute(text(f"""
            DELETE FROM implementation_power_config
            WHERE implementation_name = '{impl_name}'
        """))
        logger.info("[Migration] Removed implementation_power_config: %s", impl_name)

    logger.info("[Migration] Removed kling and veo3_duomi_v1 implementation_power_config records")
