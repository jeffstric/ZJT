"""Add VEO3 common site and Seedance power configs

Revision ID: 20260416_veo3_seedance_power
Revises: 20260409_tiered_billing
Create Date: 2026-04-16

"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy.sql import text
import json
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260416_veo3_seedance_power'
down_revision: Union[str, None] = '20260409_qwen_tiered'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加 VEO3 通用聚合站点和 Seedance 算力配置"""

    logger.info("开始添加 VEO3 通用聚合站点和 Seedance 算力配置...")

    # VEO3 通用聚合站点配置
    veo3_common_sites = [
        ('veo3_common_site1_v1', 'veo3_image_to_video', 1, 4510.0, {'fixed': 6}),
        ('veo3_common_site2_v1', 'veo3_image_to_video', 2, 4520.0, {'fixed': 6}),
        ('veo3_common_site3_v1', 'veo3_image_to_video', 3, 4530.0, {'fixed': 6}),
        ('veo3_common_site4_v1', 'veo3_image_to_video', 4, 4540.0, {'fixed': 6}),
        ('veo3_common_site5_v1', 'veo3_image_to_video', 5, 4550.0, {'fixed': 6}),
    ]

    for impl_name, driver_key, site_number, sort_order, power_config in veo3_common_sites:
        power_json = json.dumps(power_config)
        op.execute(text(f"""
            INSERT INTO implementation_power_config
            (implementation_name, driver_key, site_number, power_config, sort_order, enabled, updated_by)
            VALUES ('{impl_name}', '{driver_key}', {site_number}, '{power_json}', {sort_order}, 1, 1)
            ON DUPLICATE KEY UPDATE
                site_number = VALUES(site_number),
                power_config = VALUES(power_config),
                sort_order = VALUES(sort_order),
                enabled = VALUES(enabled)
        """))
        logger.info(f"已添加/更新 {impl_name} 的算力配置")

    # 更新 veo3_duomi_v1 的算力配置
    op.execute(text("""
        UPDATE implementation_power_config
        SET power_config = '{"fixed": 6}'
        WHERE implementation_name = 'veo3_duomi_v1' AND driver_key = 'veo3_image_to_video'
    """))
    logger.info("已更新 veo3_duomi_v1 的算力配置")

    # Seedance 算力配置
    seedance_configs = [
        (
            'seedance_1_5_pro_volcengine_v1',
            'seedance_1_5_pro_image_to_video',
            None,
            10500.0,
            {5: 46, 6: 56, 7: 66, 8: 76, 9: 85, 10: 94, 11: 103, 12: 112}
        ),
        (
            'seedance_2_0_fast_volcengine_v1',
            'seedance_2_0_fast_image_to_video',
            None,
            10600.0,
            {5: 105, 6: 126, 7: 147, 8: 168, 9: 189, 10: 210, 11: 231, 12: 252, 13: 273, 14: 294, 15: 315}
        ),
        (
            'seedance_2_0_volcengine_v1',
            'seedance_2_0_image_to_video',
            None,
            10700.0,
            {5: 250, 6: 300, 7: 350, 8: 400, 9: 450, 10: 500, 11: 550, 12: 600, 13: 650, 14: 700, 15: 750}
        ),
    ]

    for impl_name, driver_key, site_number, sort_order, power_config in seedance_configs:
        power_json = json.dumps(power_config)
        site_value = site_number if site_number is not None else 'NULL'
        op.execute(text(f"""
            INSERT INTO implementation_power_config
            (implementation_name, driver_key, site_number, power_config, sort_order, enabled, updated_by)
            VALUES ('{impl_name}', '{driver_key}', {site_value}, '{power_json}', {sort_order}, 1, 1)
            ON DUPLICATE KEY UPDATE
                site_number = VALUES(site_number),
                power_config = VALUES(power_config),
                sort_order = VALUES(sort_order),
                enabled = VALUES(enabled)
        """))
        logger.info(f"已添加/更新 {impl_name} 的算力配置")

    logger.info("VEO3 通用聚合站点和 Seedance 算力配置添加完成")


def downgrade() -> None:
    """回滚：删除新添加的算力配置"""

    logger.info("开始回滚 VEO3 通用聚合站点和 Seedance 算力配置...")

    implementations_to_remove = [
        'veo3_common_site1_v1',
        'veo3_common_site2_v1',
        'veo3_common_site3_v1',
        'veo3_common_site4_v1',
        'veo3_common_site5_v1',
        'seedance_1_5_pro_volcengine_v1',
        'seedance_2_0_fast_volcengine_v1',
        'seedance_2_0_volcengine_v1',
    ]

    for impl_name in implementations_to_remove:
        op.execute(text(f"""
            DELETE FROM implementation_power_config
            WHERE implementation_name = '{impl_name}'
        """))
        logger.info(f"已删除 {impl_name} 的算力配置")

    logger.info("回滚完成")
