"""add gpt image 2 5 power

GPT Image 2.5（sunburst / flare）14 个实现方的 implementation_power_config 种子数据：
- 多米（sunburst/flare）异步接口，固定 2 点
- zjt api 聚合站点 site_0~site_5（sunburst/flare）同步接口，固定 2 点
与管理后台 implementation_power_config 页面对应，算力值与 GPT Image 2 保持一致

Revision ID: 20260910_add_gpt_image_2_5_power
Revises: 20260909_fix_mimo_v25_pro_vl_fla
Create Date: 2026-09-10
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260910_add_gpt_image_2_5_power'
down_revision: Union[str, None] = '20260909_fix_mimo_v25_pro_vl_fla'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (implementation_name, site_number, sort_order)
_GPT_IMAGE_2_5_IMPLEMENTATIONS = [
    ('duomi_gpt_image_2_5_sunburst_v1', None, 3300.0),
    ('duomi_gpt_image_2_5_flare_v1', None, 3310.0),
    ('gpt_image_2_5_common_sunburst_site0_v1', 0, 3400.0),
    ('gpt_image_2_5_common_sunburst_site1_v1', 1, 3410.0),
    ('gpt_image_2_5_common_sunburst_site2_v1', 2, 3420.0),
    ('gpt_image_2_5_common_sunburst_site3_v1', 3, 3430.0),
    ('gpt_image_2_5_common_sunburst_site4_v1', 4, 3440.0),
    ('gpt_image_2_5_common_sunburst_site5_v1', 5, 3450.0),
    ('gpt_image_2_5_common_flare_site0_v1', 0, 3500.0),
    ('gpt_image_2_5_common_flare_site1_v1', 1, 3510.0),
    ('gpt_image_2_5_common_flare_site2_v1', 2, 3520.0),
    ('gpt_image_2_5_common_flare_site3_v1', 3, 3530.0),
    ('gpt_image_2_5_common_flare_site4_v1', 4, 3540.0),
    ('gpt_image_2_5_common_flare_site5_v1', 5, 3550.0),
]


def upgrade() -> None:
    """插入 GPT Image 2.5 各实现方的算力配置（固定 2 点，幂等）"""
    conn = op.get_bind()

    for impl_name, site_number, sort_order in _GPT_IMAGE_2_5_IMPLEMENTATIONS:
        site_value = site_number if site_number is not None else 'NULL'
        conn.execute(text(f"""
            INSERT INTO implementation_power_config
            (implementation_name, driver_key, site_number, power_config, sort_order, enabled, updated_by)
            VALUES ('{impl_name}', 'gpt_image_2_5', {site_value}, '{{"fixed": 2}}', {sort_order}, 1, 1)
            ON DUPLICATE KEY UPDATE
                power_config = VALUES(power_config),
                sort_order = VALUES(sort_order),
                enabled = VALUES(enabled)
        """))
        logger.info("[Migration] 已插入/更新 implementation_power_config: %s / gpt_image_2_5", impl_name)


def downgrade() -> None:
    """回滚：删除 GPT Image 2.5 的算力配置"""
    conn = op.get_bind()

    conn.execute(text("""
        DELETE FROM implementation_power_config
        WHERE driver_key = 'gpt_image_2_5'
    """))
    logger.info("[Migration] 已删除 gpt_image_2_5 的 implementation_power_config 记录")
