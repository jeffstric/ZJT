"""create_system_config_tables

Revision ID: 20260228_sysconfig
Revises: 20260226_workspace
Create Date: 2026-02-28 14:00:00.000000+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260228_sysconfig'
down_revision: Union[str, None] = '20260226_workspace'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库：创建 system_config 和 system_config_history 表"""
    
    # 创建 system_config 表（主配置表）
    op.execute("""
        CREATE TABLE `system_config` (
            `id` INT PRIMARY KEY AUTO_INCREMENT,
            `env` VARCHAR(32) NOT NULL DEFAULT 'dev' COMMENT '环境标识：dev/prod/test',
            `config_key` VARCHAR(256) NOT NULL COMMENT '配置键，点号分隔，如 task_queue.max_retry_count',
            `config_value` TEXT COMMENT '配置值',
            `value_type` ENUM('string', 'int', 'float', 'bool', 'json') DEFAULT 'string' COMMENT '值类型',
            `description` VARCHAR(512) COMMENT '配置描述',
            `editable` TINYINT(1) DEFAULT 1 COMMENT '是否允许通过页面修改',
            `is_sensitive` TINYINT(1) DEFAULT 0 COMMENT '是否为敏感配置（token/密钥等），敏感配置历史记录不保存明文',
            `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
            `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            `updated_by` INT COMMENT '修改人 user_id',
            UNIQUE KEY `uk_env_key` (`env`, `config_key`),
            INDEX `idx_env` (`env`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统配置表'
    """)
    
    # 创建 system_config_history 表（修改历史表）
    op.execute("""
        CREATE TABLE `system_config_history` (
            `id` INT PRIMARY KEY AUTO_INCREMENT,
            `config_id` INT NOT NULL COMMENT '关联 system_config.id',
            `env` VARCHAR(32) NOT NULL COMMENT '环境标识',
            `config_key` VARCHAR(256) NOT NULL COMMENT '配置键',
            `old_value` TEXT COMMENT '旧值（敏感配置存储脱敏值）',
            `new_value` TEXT COMMENT '新值（敏感配置存储脱敏值）',
            `value_type` VARCHAR(32) COMMENT '值类型',
            `is_sensitive` TINYINT(1) DEFAULT 0 COMMENT '标记该条历史是否为敏感配置',
            `updated_by` INT COMMENT '修改人 user_id',
            `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX `idx_config_id` (`config_id`),
            INDEX `idx_env_key` (`env`, `config_key`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统配置修改历史表'
    """)


def downgrade() -> None:
    """回滚数据库：删除 system_config 和 system_config_history 表"""
    op.execute("DROP TABLE IF EXISTS `system_config_history`")
    op.execute("DROP TABLE IF EXISTS `system_config`")
