"""
创建 implementation_stats_cache 表

用于缓存实现方统计数据，避免每次 API 请求都扫描 ai_tools 表
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS `implementation_stats_cache` (
            `id` INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            `type` INT NOT NULL COMMENT '任务类型ID',
            `impl_id` INT NOT NULL COMMENT 'implementation ID',
            `days` INT NOT NULL COMMENT '统计天数',
            `total_count` INT NOT NULL DEFAULT 0,
            `success_count` INT NOT NULL DEFAULT 0,
            `fail_count` INT NOT NULL DEFAULT 0,
            `success_rate` DECIMAL(5,2) NOT NULL DEFAULT 0.00,
            `avg_duration_ms` INT NOT NULL DEFAULT 0,
            `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY `uk_type_impl_days` (`type`, `impl_id`, `days`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

def downgrade():
    op.execute("""
        DROP TABLE IF EXISTS `implementation_stats_cache`
    """)
