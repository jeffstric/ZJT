"""
AnnouncementReads Model - Database operations for announcement_reads table
用户维度公告已读记录（与 notifications 表的全局 is_read 语义不同，勿混用）
"""
from typing import List
from datetime import datetime

from .database import execute_query, execute_update
import logging

logger = logging.getLogger(__name__)


class AnnouncementReadEntity:
    """AnnouncementRead database entity class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.announcement_id = kwargs.get('announcement_id')
        self.user_id = kwargs.get('user_id')
        self.read_at = kwargs.get('read_at')

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'announcement_id': self.announcement_id,
            'user_id': self.user_id,
            'read_at': self.read_at.isoformat() if isinstance(self.read_at, datetime) else self.read_at,
        }


class AnnouncementReadsModel:
    """AnnouncementReads database operations"""

    @staticmethod
    def mark_read(announcement_id: int, user_id: int) -> int:
        """Mark an announcement as read by a user (INSERT IGNORE 幂等，返回 1 表示新插入)"""
        sql = """
            INSERT IGNORE INTO announcement_reads (announcement_id, user_id)
            VALUES (%s, %s)
        """
        try:
            return execute_update(sql, (announcement_id, user_id))
        except Exception as e:
            logger.error(f"Failed to mark announcement {announcement_id} read for user {user_id}: {e}")
            raise

    @staticmethod
    def mark_all_read(user_id: int) -> int:
        """Mark all currently active published announcements as read for a user"""
        sql = """
            INSERT IGNORE INTO announcement_reads (announcement_id, user_id)
            SELECT a.id, %s FROM announcements a
            WHERE a.status = 'published'
              AND (a.publish_at IS NULL OR a.publish_at <= NOW())
              AND (a.expire_at IS NULL OR a.expire_at > NOW())
        """
        try:
            affected = execute_update(sql, (user_id,))
            if affected > 0:
                logger.info(f"User {user_id} marked {affected} announcements as read")
            return affected
        except Exception as e:
            logger.error(f"Failed to mark all announcements read for user {user_id}: {e}")
            raise

    @staticmethod
    def list_read_ids_by_user(user_id: int) -> List[int]:
        """Get all announcement IDs read by a user"""
        sql = "SELECT announcement_id FROM announcement_reads WHERE user_id = %s"
        try:
            results = execute_query(sql, (user_id,), fetch_all=True)
            return [row['announcement_id'] for row in (results or [])]
        except Exception as e:
            logger.error(f"Failed to list read announcements for user {user_id}: {e}")
            raise

    @staticmethod
    def delete_by_announcement(announcement_id: int) -> int:
        """Delete all read records of an announcement（公告删除时级联清理）"""
        sql = "DELETE FROM announcement_reads WHERE announcement_id = %s"
        try:
            return execute_update(sql, (announcement_id,))
        except Exception as e:
            logger.error(f"Failed to delete read records for announcement {announcement_id}: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `announcement_reads` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `announcement_id` int NOT NULL COMMENT '公告ID announcements.id',
  `user_id` int NOT NULL COMMENT '用户ID users.id',
  `read_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '已读时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_announcement_user` (`announcement_id`, `user_id`),
  KEY `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Per-user announcement read records'
"""
