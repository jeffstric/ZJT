"""Add Vidu Q3 power configs (turbo/pro, t2v/i2v/r2v)

Vidu Q3 定价（高峰价，积分/秒）：
- 图生/文生/首尾帧：turbo 540p=7 720p=12 1080p=13；pro 540p=9 720p=20 1080p=24
- 参考生：turbo 540p=4 720p=10 1080p=13；pro(viduq3) 540p=7 720p=12 1080p=15
积分汇率：500元/16000积分 = 0.03125元/积分
算力换算：ceil(积分/秒 × 0.03125 ÷ 0.04 × 1.1)，720P 为基准档（修饰符系数 1.0）
分辨率修饰符按实现方分别配置（turbo/pro 价格比例不同，任务级代码系数仅为 turbo 兜底）

Revision ID: 20260901_vidu_q3_power
Revises: 20260830_ds_vision
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.sql import text
import json
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260901_vidu_q3_power'
down_revision: Union[str, None] = '20260830_ds_vision'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加 Vidu Q3 六个实现方的算力配置（含分辨率修饰符）"""

    logger.info("[Migration] 开始添加 Vidu Q3 算力配置...")

    # (implementation_name, driver_key, sort_order, 时长算力, 分辨率修饰符)
    vidu_q3_configs = [
        # 图生视频（含首尾帧）
        ('vidu_q3_i2v_turbo_v1', 'vidu_q3_image_to_video', 1.0,
         {3: 33, 5: 55, 8: 88, 10: 110, 16: 176},
         {'540P': 0.6363, '720P': 1.0, '1080P': 1.0909, '_default': 1.0}),
        ('vidu_q3_i2v_pro_v1', 'vidu_q3_image_to_video', 2.0,
         {3: 54, 5: 90, 8: 144, 10: 180, 16: 288},
         {'540P': 0.4444, '720P': 1.0, '1080P': 1.1666, '_default': 1.0}),
        # 参考生视频
        ('vidu_q3_r2v_turbo_v1', 'vidu_q3_reference_to_video', 1.0,
         {3: 27, 5: 45, 8: 72, 10: 90, 16: 144},
         {'540P': 0.4444, '720P': 1.0, '1080P': 1.3333, '_default': 1.0}),
        ('vidu_q3_r2v_pro_v1', 'vidu_q3_reference_to_video', 2.0,
         {3: 33, 5: 55, 8: 88, 10: 110, 16: 176},
         {'540P': 0.6363, '720P': 1.0, '1080P': 1.1818, '_default': 1.0}),
        # 文生视频
        ('vidu_q3_t2v_turbo_v1', 'vidu_q3_text_to_video', 1.0,
         {3: 33, 5: 55, 8: 88, 10: 110, 16: 176},
         {'540P': 0.6363, '720P': 1.0, '1080P': 1.0909, '_default': 1.0}),
        ('vidu_q3_t2v_pro_v1', 'vidu_q3_text_to_video', 2.0,
         {3: 54, 5: 90, 8: 144, 10: 180, 16: 288},
         {'540P': 0.4444, '720P': 1.0, '1080P': 1.1666, '_default': 1.0}),
    ]

    for impl_name, driver_key, sort_order, powers, resolution_modifiers in vidu_q3_configs:
        power_config = {str(d): p for d, p in powers.items()}
        power_config['modifiers'] = {'resolution': resolution_modifiers}
        power_json = json.dumps(power_config)
        op.execute(text(f"""
            INSERT INTO implementation_power_config
            (implementation_name, driver_key, site_number, power_config, sort_order, enabled, updated_by)
            VALUES ('{impl_name}', '{driver_key}', NULL, '{power_json}', {sort_order}, 1, 1)
            ON DUPLICATE KEY UPDATE
                power_config = VALUES(power_config),
                sort_order = VALUES(sort_order),
                enabled = VALUES(enabled)
        """))
        logger.info(f"[Migration] 已添加/更新 {impl_name} 的算力配置")

    logger.info("[Migration] Vidu Q3 算力配置添加完成")


def downgrade() -> None:
    """回滚：删除 Vidu Q3 算力配置"""

    logger.info("[Migration] 开始回滚 Vidu Q3 算力配置...")

    implementations_to_remove = [
        'vidu_q3_i2v_turbo_v1',
        'vidu_q3_i2v_pro_v1',
        'vidu_q3_r2v_turbo_v1',
        'vidu_q3_r2v_pro_v1',
        'vidu_q3_t2v_turbo_v1',
        'vidu_q3_t2v_pro_v1',
    ]

    for impl_name in implementations_to_remove:
        op.execute(text(f"""
            DELETE FROM implementation_power_config
            WHERE implementation_name = '{impl_name}'
        """))
        logger.info(f"[Migration] 已删除 {impl_name} 的算力配置")

    logger.info("[Migration] 回滚完成")
