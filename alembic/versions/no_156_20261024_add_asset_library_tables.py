"""add asset library tables

新建资产库 4 张表（见 docs/backend/asset_library.md）：
- asset_group            资产分组（目录），全局共享
- asset_library          资产记录（生成图片收藏，永久存放，不受媒体缓存清理）
- asset_permission_member 资产指定成员权限（view/edit 为 specified 时生效）
- asset_library_quota    用户资产库容量配额（管理员逐人控制，0=不限）

Revision ID: 20261024_add_asset_library_table
Revises: 20261021_add_compose_jobs
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261024_add_asset_library_table'
down_revision: Union[str, None] = '20261021_add_compose_jobs'
branch_labels: tuple | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新建资产库 4 张表（幂等）。"""
    conn = op.get_bind()

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS `asset_group` (
          `id` int NOT NULL AUTO_INCREMENT,
          `name` varchar(50) NOT NULL COMMENT '分组名称（全局唯一，共享目录）',
          `creator_user_id` int NOT NULL COMMENT '创建者用户 ID',
          `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
          `update_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_name` (`name`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='资产库分组（目录）表-全局共享'
    """))
    logger.info("[Migration] Created table asset_group")

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS `asset_library` (
          `id` int NOT NULL AUTO_INCREMENT,
          `user_id` int NOT NULL COMMENT '添加者用户 ID（容量计入该用户）',
          `group_id` int DEFAULT NULL COMMENT '资产分组 asset_group.id（NULL=未分组）',
          `asset_type` varchar(20) NOT NULL DEFAULT 'image' COMMENT '资产类型：image（预留 video/audio）',
          `name` varchar(200) NOT NULL COMMENT '资产名称',
          `source_url` text COMMENT '原始生成地址（溯源用）',
          `file_path` varchar(500) NOT NULL COMMENT '本地存储路径（相对 upload 目录，如 asset_library/1/xxx.png）',
          `file_size` bigint NOT NULL DEFAULT 0 COMMENT '文件字节数（配额统计口径）',
          `view_permission` varchar(20) NOT NULL DEFAULT 'private' COMMENT '查看权限：private/specified/public',
          `edit_permission` varchar(20) NOT NULL DEFAULT 'private' COMMENT '编辑权限：private/specified/public',
          `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
          `update_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
          PRIMARY KEY (`id`),
          KEY `idx_user_create` (`user_id`,`create_at`),
          KEY `idx_group` (`group_id`),
          KEY `idx_type` (`asset_type`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='资产库表-用户收藏的生成产物，永久存放'
    """))
    logger.info("[Migration] Created table asset_library")

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS `asset_permission_member` (
          `id` int NOT NULL AUTO_INCREMENT,
          `asset_id` int NOT NULL COMMENT '资产 asset_library.id',
          `user_id` int NOT NULL COMMENT '被指定成员用户 ID',
          `perm_type` varchar(10) NOT NULL COMMENT '权限类型：view(可看)/edit(可编辑)',
          `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_asset_user_perm` (`asset_id`,`user_id`,`perm_type`),
          KEY `idx_user` (`user_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='资产库指定成员权限表'
    """))
    logger.info("[Migration] Created table asset_permission_member")

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS `asset_library_quota` (
          `id` int NOT NULL AUTO_INCREMENT,
          `user_id` int NOT NULL COMMENT '用户 ID',
          `quota_bytes` bigint NOT NULL DEFAULT 2147483648 COMMENT '资产库容量上限（字节，0=不限制，默认 2GB）',
          `used_bytes` bigint NOT NULL DEFAULT 0 COMMENT '已用资产库容量（字节，随加入/清除增减）',
          `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
          `update_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_user` (`user_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户资产库容量配额表'
    """))
    logger.info("[Migration] Created table asset_library_quota")


def downgrade() -> None:
    """回滚：删除资产库 4 张表（权限成员表先删，语义上从属于资产表）。"""
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS `asset_permission_member`"))
    conn.execute(text("DROP TABLE IF EXISTS `asset_library_quota`"))
    conn.execute(text("DROP TABLE IF EXISTS `asset_library`"))
    conn.execute(text("DROP TABLE IF EXISTS `asset_group`"))
    logger.info("[Migration] Dropped asset library tables")
