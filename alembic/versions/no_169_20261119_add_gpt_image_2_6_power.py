"""add gpt image 2 6 power

GPT Image 2.6（sunburst / flare 两个独立模型，各 7 个实现方）的
implementation_power_config 种子数据：
- gpt_image_2_6_sunburst：多米（异步）+ 聚合站点 site_0~site_5（同步）
- gpt_image_2_6_flare：多米（异步）+ 聚合站点 site_0~site_5（同步）
固定 2 点算力，与管理后台 implementation_power_config 页面对应，与 GPT Image 2.5 定价保持一致

Revision ID: 20261119_add_gpt_image_2_6_power
Revises: 20261119_add_user_group
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261119_add_gpt_image_2_6_power'
down_revision: Union[str, None] = '20261119_add_user_group'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (implementation_name, driver_key, site_number, sort_order)
_GPT_IMAGE_2_6_IMPLEMENTATIONS = [
    ('duomi_gpt_image_2_6_sunburst_v1', 'gpt_image_2_6_sunburst', None, 3600.0),
    ('gpt_image_2_6_common_sunburst_site0_v1', 'gpt_image_2_6_sunburst', 0, 3700.0),
    ('gpt_image_2_6_common_sunburst_site1_v1', 'gpt_image_2_6_sunburst', 1, 3710.0),
    ('gpt_image_2_6_common_sunburst_site2_v1', 'gpt_image_2_6_sunburst', 2, 3720.0),
    ('gpt_image_2_6_common_sunburst_site3_v1', 'gpt_image_2_6_sunburst', 3, 3730.0),
    ('gpt_image_2_6_common_sunburst_site4_v1', 'gpt_image_2_6_sunburst', 4, 3740.0),
    ('gpt_image_2_6_common_sunburst_site5_v1', 'gpt_image_2_6_sunburst', 5, 3750.0),
    ('duomi_gpt_image_2_6_flare_v1', 'gpt_image_2_6_flare', None, 3610.0),
    ('gpt_image_2_6_common_flare_site0_v1', 'gpt_image_2_6_flare', 0, 3800.0),
    ('gpt_image_2_6_common_flare_site1_v1', 'gpt_image_2_6_flare', 1, 3810.0),
    ('gpt_image_2_6_common_flare_site2_v1', 'gpt_image_2_6_flare', 2, 3820.0),
    ('gpt_image_2_6_common_flare_site3_v1', 'gpt_image_2_6_flare', 3, 3830.0),
    ('gpt_image_2_6_common_flare_site4_v1', 'gpt_image_2_6_flare', 4, 3840.0),
    ('gpt_image_2_6_common_flare_site5_v1', 'gpt_image_2_6_flare', 5, 3850.0),
]


def upgrade() -> None:
    """插入 GPT Image 2.6 各实现方的算力配置（固定 2 点，幂等）"""
    conn = op.get_bind()

    for impl_name, driver_key, site_number, sort_order in _GPT_IMAGE_2_6_IMPLEMENTATIONS:
        site_value = site_number if site_number is not None else 'NULL'
        conn.execute(text(f"""
            INSERT INTO implementation_power_config
            (implementation_name, driver_key, site_number, power_config, sort_order, enabled, updated_by)
            VALUES ('{impl_name}', '{driver_key}', {site_value}, '{{"fixed": 2}}', {sort_order}, 1, 1)
            ON DUPLICATE KEY UPDATE
                power_config = VALUES(power_config),
                sort_order = VALUES(sort_order),
                enabled = VALUES(enabled)
        """))
        logger.info("[Migration] 已插入/更新 implementation_power_config: %s / %s", impl_name, driver_key)


def downgrade() -> None:
    """回滚：删除 GPT Image 2.6 的算力配置"""
    conn = op.get_bind()

    conn.execute(text("""
        DELETE FROM implementation_power_config
        WHERE driver_key IN ('gpt_image_2_6_sunburst', 'gpt_image_2_6_flare')
    """))
    logger.info("[Migration] 已删除 GPT Image 2.6 的 implementation_power_config 记录")
