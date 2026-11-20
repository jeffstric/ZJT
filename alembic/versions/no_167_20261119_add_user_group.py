"""新增用户分组：user_group 表 + users.group_id 列

管理后台支持管理员创建用户分组、把用户归入分组，并按月汇总各分组
算力消耗（下钻到组内用户）。用户与分组为多对一：users.group_id 为
NULL 表示未分组。删除分组时应用层先把组内用户 group_id 置 NULL。

Revision ID: 20261119_add_user_group
Revises: 20261111_add_aigc_popup_notice
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261119_add_user_group'
down_revision: Union[str, None] = '20261111_add_aigc_popup_notice'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    return result.scalar() > 0


def _index_exists(conn, table: str, index: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :index"
    ), {"table": table, "index": index})
    return result.scalar() > 0


def upgrade() -> None:
    """建 user_group 表；users 加 group_id 列与索引（幂等）"""
    conn = op.get_bind()

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS `user_group` (
          `id` int NOT NULL AUTO_INCREMENT,
          `name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '分组名称',
          `remark` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '分组备注',
          `create_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
          `update_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
          PRIMARY KEY (`id`) USING BTREE,
          UNIQUE KEY `uk_name` (`name`) USING BTREE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户分组（管理员创建）'
    """))
    logger.info("[Migration] ensured table user_group")

    if not _column_exists(conn, "users", "group_id"):
        conn.execute(text(
            "ALTER TABLE `users` ADD COLUMN `group_id` int DEFAULT NULL "
            "COMMENT '所属用户分组id（NULL=未分组）' AFTER `zjt_token_expire_at`"
        ))
        logger.info("[Migration] added users.group_id")

    if not _index_exists(conn, "users", "idx_group_id"):
        conn.execute(text("CREATE INDEX `idx_group_id` ON `users` (`group_id`)"))
        logger.info("[Migration] added index users.idx_group_id")


def downgrade() -> None:
    """回滚：删除 users.group_id（组员自动回到未分组），删除 user_group 表"""
    conn = op.get_bind()

    if _index_exists(conn, "users", "idx_group_id"):
        conn.execute(text("DROP INDEX `idx_group_id` ON `users`"))
        logger.info("[Migration] dropped index users.idx_group_id")

    if _column_exists(conn, "users", "group_id"):
        conn.execute(text("ALTER TABLE `users` DROP COLUMN `group_id`"))
        logger.info("[Migration] dropped users.group_id")

    conn.execute(text("DROP TABLE IF EXISTS `user_group`"))
    logger.info("[Migration] dropped table user_group")
