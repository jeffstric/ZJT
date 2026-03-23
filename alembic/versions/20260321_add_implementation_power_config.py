"""Add implementation_power_config table

Revision ID: 20260321_impl_power
Revises: 20260318_cleanup_slots
Create Date: 2026-03-21 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision = '20260321_impl_power'
down_revision = '20260318_cleanup_slots'
branch_labels = None
depends_on = None


def upgrade():
    """创建实现方算力配置表，支持按时长配置算力"""

    logger.info("开始创建 implementation_power_config 表...")

    # 创建表，使用自增ID作为主键
    # duration 为 NULL 表示固定算力
    op.execute(text("""
        CREATE TABLE implementation_power_config (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT '自增ID',
            implementation_name VARCHAR(100) NOT NULL COMMENT '实现方名称',
            driver_key VARCHAR(100) NOT NULL COMMENT 'DriverKey，用于分组排序',
            site_number INT NULL COMMENT '聚合站点编号(1-5)，非聚合站点为NULL',
            duration INT NULL COMMENT '时长（秒），NULL表示固定算力',
            computing_power INT NULL COMMENT '算力值',
            sort_order FLOAT NOT NULL DEFAULT 999999.0 COMMENT '排序顺序',
            enabled TINYINT(1) DEFAULT 1 COMMENT '是否启用(1=启用,0=禁用)',
            updated_by INT NULL COMMENT '更新人ID',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            INDEX idx_driver_key_sort_order (driver_key, sort_order),
            INDEX idx_implementation_name (implementation_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='实现方算力配置表'
    """))

    # 初始化所有实现方的默认配置
    implementations = [
        # 多米供应商 - DriverKey: DOMI
        ('sora2_duomi_v1', 'DOMI', None, None, 1000.0),
        ('kling_duomi_v1', 'DOMI', None, None, 2000.0),
        ('gemini_duomi_v1', 'DOMI', None, None, 3000.0),
        ('veo3_duomi_v1', 'DOMI', None, None, 4000.0),

        # RunningHub 供应商 - DriverKey: RUNNINGHUB
        ('ltx2_runninghub_v1', 'RUNNINGHUB', None, None, 5000.0),
        ('wan22_runninghub_v1', 'RUNNINGHUB', None, None, 6000.0),
        ('digital_human_runninghub_v1', 'RUNNINGHUB', None, None, 7000.0),

        # Vidu 供应商 - DriverKey: VIDU
        ('vidu_default', 'VIDU', None, None, 8000.0),
        ('vidu_q2', 'VIDU', None, None, 9000.0),

        # Seedream 供应商 - DriverKey: SEEDREAM
        ('seedream5_volcengine_v1', 'SEEDREAM', None, None, 10000.0),

        # API 聚合站站点 - DriverKey: GEMINI_IMAGE_PREVIEW
        ('gemini_image_preview_site1_v1', 'GEMINI_IMAGE_PREVIEW', 1, None, 11000.0),
        ('gemini_image_preview_site2_v1', 'GEMINI_IMAGE_PREVIEW', 2, None, 12000.0),
        ('gemini_image_preview_site3_v1', 'GEMINI_IMAGE_PREVIEW', 3, None, 13000.0),
        ('gemini_image_preview_site4_v1', 'GEMINI_IMAGE_PREVIEW', 4, None, 14000.0),
        ('gemini_image_preview_site5_v1', 'GEMINI_IMAGE_PREVIEW', 5, None, 15000.0),
    ]

    logger.info(f"开始初始化 {len(implementations)} 个实现方配置...")

    for impl_name, driver_key, site_number, duration, sort_order in implementations:
        try:
            op.execute(text(f"""
                INSERT INTO implementation_power_config
                (implementation_name, driver_key, site_number, duration, sort_order, enabled, updated_by)
                VALUES ('{impl_name}', '{driver_key}', {site_number if site_number is not None else 'NULL'}, {duration if duration is not None else 'NULL'}, {sort_order}, 1, 1)
            """))
            logger.info(f"已初始化实现方 {impl_name} 的配置")
        except Exception as e:
            logger.error(f"初始化实现方 {impl_name} 时出错: {e}")

    logger.info("实现方配置初始化完成")


def downgrade():
    """回滚：删除实现方配置表"""
    op.execute(text("DROP TABLE IF EXISTS implementation_power_config"))
