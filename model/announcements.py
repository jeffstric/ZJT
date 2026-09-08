"""
Announcements Model - Database operations for announcements table
本站公告：管理员在后台创建/发布/编辑/下线的通知（区别于 notifications 表的远程拉取公告）
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
import json

from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class AnnouncementStatus:
    """公告状态常量"""
    DRAFT = 'draft'
    PUBLISHED = 'published'
    OFFLINE = 'offline'


VALID_LEVELS = ('info', 'success', 'warning', 'error')


class AnnouncementEntity:
    """Announcement database entity class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.title = kwargs.get('title', '')
        self.content = kwargs.get('content', '')
        self.link_url = kwargs.get('link_url')
        self.link_text = kwargs.get('link_text')

        # Deserialize images from JSON (list of urls)
        images_json = kwargs.get('images')
        if isinstance(images_json, str) and images_json:
            try:
                self.images = json.loads(images_json)
            except json.JSONDecodeError:
                self.images = []
        else:
            self.images = images_json or []

        self.level = kwargs.get('level', 'info')
        self.status = kwargs.get('status', AnnouncementStatus.DRAFT)
        self.publish_at = kwargs.get('publish_at')
        self.expire_at = kwargs.get('expire_at')
        self.created_by = kwargs.get('created_by')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
        # 由 LEFT JOIN announcement_reads 填充（用户侧查询），无 JOIN 时为 None
        self.is_read = bool(kwargs.get('read_id'))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API output"""
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'link_url': self.link_url,
            'link_text': self.link_text,
            'images': self.images,
            'level': self.level,
            'status': self.status,
            'publish_at': self.publish_at.isoformat() if self.publish_at else None,
            'expire_at': self.expire_at.isoformat() if self.expire_at else None,
            'created_by': self.created_by,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# 当前有效的已发布公告条件（发布中 + 定时窗口 + 未过期），用户侧查询复用
_PUBLISHED_ACTIVE_WHERE = """
    a.status = 'published'
    AND (a.publish_at IS NULL OR a.publish_at <= NOW())
    AND (a.expire_at IS NULL OR a.expire_at > NOW())
"""


class AnnouncementsModel:
    """Announcements database operations"""

    @staticmethod
    def create(
        title: str,
        content: str = '',
        link_url: str = None,
        link_text: str = None,
        images: list = None,
        level: str = 'info',
        status: str = AnnouncementStatus.DRAFT,
        publish_at: str = None,
        expire_at: str = None,
        created_by: int = 0,
    ) -> int:
        """Create a new announcement, returns inserted record ID"""
        sql = """
            INSERT INTO announcements
            (title, content, link_url, link_text, images, level, status, publish_at, expire_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        images_json = json.dumps(images or [], ensure_ascii=False)
        params = (title, content, link_url, link_text, images_json, level, status,
                  publish_at, expire_at, created_by)

        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created announcement: {title} (id={record_id})")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create announcement: {e}")
            raise

    @staticmethod
    def update(
        announcement_id: int,
        title: str,
        content: str = '',
        link_url: str = None,
        link_text: str = None,
        images: list = None,
        level: str = 'info',
        publish_at: str = None,
        expire_at: str = None,
    ) -> int:
        """Update an announcement's editable fields (status 走 update_status 状态机)"""
        sql = """
            UPDATE announcements
            SET title = %s, content = %s, link_url = %s, link_text = %s,
                images = %s, level = %s, publish_at = %s, expire_at = %s
            WHERE id = %s
        """
        images_json = json.dumps(images or [], ensure_ascii=False)
        params = (title, content, link_url, link_text, images_json, level,
                  publish_at, expire_at, announcement_id)

        try:
            affected = execute_update(sql, params)
            if affected > 0:
                logger.info(f"Updated announcement {announcement_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to update announcement {announcement_id}: {e}")
            raise

    @staticmethod
    def update_status(announcement_id: int, status: str) -> int:
        """Update announcement status (draft/published/offline)"""
        sql = "UPDATE announcements SET status = %s WHERE id = %s"
        try:
            return execute_update(sql, (status, announcement_id))
        except Exception as e:
            logger.error(f"Failed to update announcement {announcement_id} status: {e}")
            raise

    @staticmethod
    def get_by_id(announcement_id: int) -> Optional[AnnouncementEntity]:
        """Get an announcement by ID"""
        sql = "SELECT * FROM announcements WHERE id = %s"
        try:
            result = execute_query(sql, (announcement_id,), fetch_one=True)
            return AnnouncementEntity(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get announcement {announcement_id}: {e}")
            raise

    @staticmethod
    def list_admin(page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """List all announcements with pagination (admin use)"""
        offset = (page - 1) * page_size

        count_sql = "SELECT COUNT(*) AS total FROM announcements"
        try:
            count_result = execute_query(count_sql, fetch_one=True)
            total = count_result['total'] if count_result else 0
        except Exception as e:
            logger.error(f"Failed to count announcements: {e}")
            raise

        sql = """
            SELECT * FROM announcements
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        try:
            results = execute_query(sql, (page_size, offset), fetch_all=True)
            items = [AnnouncementEntity(**row) for row in (results or [])]
            return {
                'items': items,
                'total': total,
                'page': page,
                'page_size': page_size,
            }
        except Exception as e:
            logger.error(f"Failed to list announcements: {e}")
            raise

    @staticmethod
    def list_for_user(user_id: int, limit: int = 50) -> List[AnnouncementEntity]:
        """List published & active announcements for a user, with per-user read state (LEFT JOIN)"""
        sql = f"""
            SELECT a.*, r.id AS read_id
            FROM announcements a
            LEFT JOIN announcement_reads r
              ON r.announcement_id = a.id AND r.user_id = %s
            WHERE {_PUBLISHED_ACTIVE_WHERE}
            ORDER BY a.created_at DESC
            LIMIT %s
        """
        try:
            results = execute_query(sql, (user_id, limit), fetch_all=True)
            return [AnnouncementEntity(**row) for row in (results or [])]
        except Exception as e:
            logger.error(f"Failed to list announcements for user {user_id}: {e}")
            raise

    @staticmethod
    def get_unread_count_for_user(user_id: int) -> int:
        """Count published & active announcements not yet read by the user"""
        sql = f"""
            SELECT COUNT(*) AS cnt FROM announcements a
            WHERE {_PUBLISHED_ACTIVE_WHERE}
              AND NOT EXISTS (
                SELECT 1 FROM announcement_reads r
                WHERE r.announcement_id = a.id AND r.user_id = %s
              )
        """
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            return result['cnt'] if result else 0
        except Exception as e:
            logger.error(f"Failed to count unread announcements for user {user_id}: {e}")
            raise

    @staticmethod
    def delete_by_id(announcement_id: int) -> int:
        """Delete an announcement by ID (reads 由 service 层一并清理)"""
        sql = "DELETE FROM announcements WHERE id = %s"
        try:
            return execute_update(sql, (announcement_id,))
        except Exception as e:
            logger.error(f"Failed to delete announcement {announcement_id}: {e}")
            raise


CREATE_TABLE_SQL = """
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
"""
