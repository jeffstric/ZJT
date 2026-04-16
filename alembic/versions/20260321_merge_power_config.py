"""Merge duration and computing_power into power_config JSON field

Revision ID: 20260321_merge_power_config
Revises: 20260321_impl_power
Create Date: 2026-03-21 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text
import logging
import json

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = '20260321_merge_power_config'
down_revision = '20260325_094948'
branch_labels = None
depends_on = None


def upgrade():
    """重构表结构，将 duration 和 computing_power 合并为 power_config JSON 字段"""

    logger.info("开始重构 implementation_power_config 表...")

    # 删除旧表
    op.execute(text("DROP TABLE IF EXISTS implementation_power_config"))

    # 创建新表
    op.execute(text("""
        CREATE TABLE implementation_power_config (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增ID',
            implementation_name VARCHAR(100) NOT NULL UNIQUE COMMENT '实现方名称',
            driver_key VARCHAR(100) NOT NULL COMMENT 'DriverKey，用于分组排序',
            site_number INT NULL COMMENT '聚合站点编号(1-5)，非聚合站点为NULL',
            power_config JSON NULL COMMENT '算力配置JSON，格式: {"5": 38, "10": 70} 或 {"fixed": 100}',
            sort_order FLOAT NOT NULL DEFAULT 999999.0 COMMENT '排序顺序',
            enabled TINYINT(1) DEFAULT 1 COMMENT '是否启用(1=启用,0=禁用)',
            display_name VARCHAR(200) NULL COMMENT '显示名称',
            updated_by INT NULL COMMENT '更新人ID',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            INDEX idx_driver_key_sort_order (driver_key, sort_order),
            INDEX idx_implementation_name (implementation_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='实现方配置表'
    """))

    # 初始化实现方配置数据
    # 从配置中读取 default_computing_power 并写入 power_config
    implementations = [
        # 多米供应商
        ('sora2_duomi_v1', 'sora2_image_to_video', None, 1000.0, None),
        ('kling_duomi_v1', 'kling_image_to_video', None, 2000.0, None),
        ('gemini_duomi_v1', 'gemini_image_edit', None, 3000.0, None),
        ('veo3_duomi_v1', 'veo3_image_to_video', None, 4000.0, None),
        # RunningHub 供应商
        ('ltx2_runninghub_v1', 'ltx2_image_to_video', None, 5000.0, None),
        ('wan22_runninghub_v1', 'wan22_image_to_video', None, 6000.0, None),
        ('digital_human_runninghub_v1', 'digital_human', None, 7000.0, None),
        # Vidu
        ('vidu_default', 'vidu_image_to_video', None, 8000.0, None),
        ('vidu_q2', 'vidu_q2_image_to_video', None, 9000.0, None),
        # Seedream
        ('seedream5_volcengine_v1', 'seedream_text_to_image', None, 10000.0, None),
        # API 聚合站
        ('gemini_image_preview_site1_v1', 'gemini_image_preview', 1, 11000.0, None),
        ('gemini_image_preview_site2_v1', 'gemini_image_preview', 2, 12000.0, None),
        ('gemini_image_preview_site3_v1', 'gemini_image_preview', 3, 13000.0, None),
        ('gemini_image_preview_site4_v1', 'gemini_image_preview', 4, 14000.0, None),
        ('gemini_image_preview_site5_v1', 'gemini_image_preview', 5, 15000.0, None),
    ]

    logger.info(f"开始初始化 {len(implementations)} 个实现方配置...")

    for impl_name, driver_key, site_number, sort_order, _ in implementations:
        try:
            # 获取代码默认算力配置
            from config.unified_config import ALL_IMPLEMENTATIONS
            default_power = None
            if impl_name in ALL_IMPLEMENTATIONS:
                impl_config = ALL_IMPLEMENTATIONS[impl_name]
                default_power = impl_config.get('default_computing_power')

            # 构建 power_config JSON
            power_config_json = None
            if default_power:
                if isinstance(default_power, dict):
                    # 检查是否是固定算力还是按时长区分
                    if 'fixed' in default_power or len(default_power) == 1:
                        # 固定算力
                        power_config_json = json.dumps({"fixed": list(default_power.values())[0]})
                    else:
                        # 按时长区分
                        power_config_json = json.dumps(default_power)
                else:
                    # 单一数值
                    power_config_json = json.dumps({"fixed": default_power})

            # 构建插入语句，正确处理 NULL 值
            power_value = f"'{power_config_json}'" if power_config_json else "NULL"
            op.execute(text(f"""
                INSERT INTO implementation_power_config
                (implementation_name, driver_key, site_number, power_config, sort_order, enabled, updated_by)
                VALUES ('{impl_name}', '{driver_key}', {site_number if site_number is not None else 'NULL'},
                        {power_value},
                        {sort_order}, 1, 1)
            """))
            logger.info(f"已初始化实现方 {impl_name} 的配置")
        except Exception as e:
            logger.error(f"初始化实现方 {impl_name} 时出错: {e}")

    logger.info("实现方配置初始化完成")


def downgrade():
    """回滚：删除实现方配置表"""
    op.execute(text("DROP TABLE IF EXISTS implementation_power_config"))
