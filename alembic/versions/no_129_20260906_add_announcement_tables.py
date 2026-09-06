"""add announcement tables

Revision ID: 20260906_add_announcement_tables
Revises: 20260905_ai_audio_speed
Create Date: 2026-09-06

本站公告体系：
- announcements：管理员发布/编辑的站内公告（标题/正文/链接/图片/级别/状态/发布与有效期窗口）
- announcement_reads：用户维度已读记录（uk: announcement_id + user_id）
与既有 notifications 表（远程拉取的全局公告）相互独立。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260906_add_announcement_tables'
down_revision: Union[str, None] = '20260905_ai_audio_speed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建本站公告表 announcements 与用户已读表 announcement_reads（幂等）"""
    conn = op.get_bind()

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS `announcements` (
          `id` int NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
          `title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '公告标题',
          `content` text COLLATE utf8mb4_unicode_ci COMMENT '公告正文',
          `link_url` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '跳转链接(可选)',
          `link_text` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '链接展示文字(可选)',
          `images` text COLLATE utf8mb4_unicode_ci COMMENT '图片 URL JSON 数组(可选)',
          `level` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'info' COMMENT '级别: info/success/warning/error',
          `status` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'draft' COMMENT '状态: draft/published/offline',
          `publish_at` datetime DEFAULT NULL COMMENT '定时发布时间(NULL=立即)',
          `expire_at` datetime DEFAULT NULL COMMENT '失效时间(NULL=长期有效)',
          `created_by` int NOT NULL COMMENT '创建人 users.id',
          `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
          `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
          PRIMARY KEY (`id`),
          KEY `idx_status` (`status`),
          KEY `idx_created_at` (`created_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Admin published announcements'
    """))
    logger.info("[Migration] announcements 表已就绪")

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS `announcement_reads` (
          `id` int NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
          `announcement_id` int NOT NULL COMMENT '公告ID announcements.id',
          `user_id` int NOT NULL COMMENT '用户ID users.id',
          `read_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '已读时间',
          PRIMARY KEY (`id`),
          UNIQUE KEY `uk_announcement_user` (`announcement_id`, `user_id`),
          KEY `idx_user_id` (`user_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Per-user announcement read records'
    """))
    logger.info("[Migration] announcement_reads 表已就绪")


def downgrade() -> None:
    """回滚：删除两张公告表"""
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS `announcement_reads`"))
    conn.execute(text("DROP TABLE IF EXISTS `announcements`"))
    logger.info("[Migration] 已回滚 announcements / announcement_reads 表")
