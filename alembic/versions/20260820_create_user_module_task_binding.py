"""新建 user_module_task_binding 表：用户模块与核心模型条目的实现方绑定

Revision ID: 20260820_module_binding
Revises: 20260811_user_modules
Create Date: 2026-08-20

把已激活用户模块的 operation 能力注册为核心任务条目的可选实现方，
使模块模型出现在业务界面的模型下拉中并走统一的任务调度链路。
"""
from typing import Sequence, Union

from alembic import op

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260820_module_binding'
down_revision: Union[str, None] = '20260811_user_modules'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库：创建 user_module_task_binding 表"""
    op.execute("""
        CREATE TABLE IF NOT EXISTS `user_module_task_binding` (
          `id` BIGINT NOT NULL AUTO_INCREMENT,
          `module_id` VARCHAR(128) NOT NULL,
          `operation` VARCHAR(64) NOT NULL,
          `task_id` INT UNSIGNED NOT NULL,
          `implementation_id` INT UNSIGNED NOT NULL,
          `implementation_name` VARCHAR(256) NOT NULL,
          `display_name` VARCHAR(256) NOT NULL DEFAULT '',
          `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_user_module_binding_impl_id` (`implementation_id`),
          UNIQUE KEY `uk_user_module_binding_impl_name` (`implementation_name`),
          UNIQUE KEY `uk_user_module_binding_unique` (`module_id`, `operation`, `task_id`),
          KEY `idx_user_module_binding_module` (`module_id`),
          KEY `idx_user_module_binding_task` (`task_id`),
          CONSTRAINT `fk_user_module_binding_module` FOREIGN KEY (`module_id`)
            REFERENCES `user_module` (`module_id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        COMMENT='用户模块与核心模型条目的实现方绑定'
    """)
    logger.info("[Migration] 创建 user_module_task_binding 表")


def downgrade() -> None:
    """回滚数据库：删除 user_module_task_binding 表"""
    op.execute("DROP TABLE IF EXISTS `user_module_task_binding`")
    logger.info("[Migration] 删除 user_module_task_binding 表")
