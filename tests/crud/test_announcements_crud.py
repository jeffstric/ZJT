"""
Announcements CRUD 单元测试

测试 model/announcements.py 与 model/announcement_reads.py 的实体和模型逻辑。
使用 mock 隔离数据库操作。
"""
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from model.announcements import (
    AnnouncementEntity,
    AnnouncementsModel,
    AnnouncementStatus,
    VALID_LEVELS,
)
from model.announcement_reads import (
    AnnouncementReadEntity,
    AnnouncementReadsModel,
)


class TestAnnouncementEntity(unittest.TestCase):
    """测试 AnnouncementEntity 实体类"""

    def test_images_json_parse(self):
        entity = AnnouncementEntity(images='["/upload/a.png", "/upload/b.png"]')
        self.assertEqual(entity.images, ["/upload/a.png", "/upload/b.png"])

    def test_images_invalid_json(self):
        entity = AnnouncementEntity(images='not json')
        self.assertEqual(entity.images, [])

    def test_images_none_or_empty(self):
        self.assertEqual(AnnouncementEntity(images=None).images, [])
        self.assertEqual(AnnouncementEntity(images='').images, [])
        self.assertEqual(AnnouncementEntity(images=[]).images, [])

    def test_defaults(self):
        entity = AnnouncementEntity()
        self.assertEqual(entity.title, '')
        self.assertEqual(entity.content, '')
        self.assertEqual(entity.level, 'info')
        self.assertEqual(entity.status, AnnouncementStatus.DRAFT)
        self.assertIsNone(entity.link_url)
        self.assertEqual(entity.images, [])
        self.assertFalse(entity.is_read)

    def test_is_read_from_join(self):
        entity = AnnouncementEntity(read_id=3)
        self.assertTrue(entity.is_read)
        entity = AnnouncementEntity(read_id=None)
        self.assertFalse(entity.is_read)

    def test_to_dict(self):
        now = datetime(2026, 9, 6, 10, 30, 0)
        entity = AnnouncementEntity(
            id=1,
            title="智剧通9月征稿",
            content="详情见链接",
            link_url="https://example.com",
            link_text="报名入口",
            images='["/upload/announcement/202609/x.png"]',
            level="warning",
            status="published",
            publish_at=now,
            expire_at=None,
            created_by=1,
            created_at=now,
            updated_at=now,
        )
        d = entity.to_dict()
        self.assertEqual(d['title'], "智剧通9月征稿")
        self.assertEqual(d['images'], ["/upload/announcement/202609/x.png"])
        self.assertEqual(d['link_url'], "https://example.com")
        self.assertEqual(d['link_text'], "报名入口")
        self.assertEqual(d['status'], "published")
        self.assertEqual(d['publish_at'], now.isoformat())
        self.assertIsNone(d['expire_at'])
        self.assertFalse(d['is_read'])

    def test_valid_levels(self):
        self.assertEqual(VALID_LEVELS, ('info', 'success', 'warning', 'error'))


class TestAnnouncementsModel(unittest.TestCase):
    """测试 AnnouncementsModel 数据操作（mock 数据库）"""

    @patch('model.announcements.execute_insert')
    def test_create(self, mock_insert):
        mock_insert.return_value = 9
        record_id = AnnouncementsModel.create(
            title="标题",
            content="正文",
            images=["/upload/a.png"],
            level="info",
            status=AnnouncementStatus.PUBLISHED,
            created_by=1,
        )
        self.assertEqual(record_id, 9)
        sql, params = mock_insert.call_args.args
        self.assertIn("INSERT INTO announcements", sql)
        # images 以 JSON 字符串入库
        self.assertEqual(json.loads(params[4]), ["/upload/a.png"])
        self.assertEqual(params[6], AnnouncementStatus.PUBLISHED)

    @patch('model.announcements.execute_update')
    def test_update_status(self, mock_update):
        mock_update.return_value = 1
        affected = AnnouncementsModel.update_status(5, AnnouncementStatus.OFFLINE)
        self.assertEqual(affected, 1)
        sql, params = mock_update.call_args.args
        self.assertIn("SET status = %s", sql)
        self.assertEqual(params, (AnnouncementStatus.OFFLINE, 5))

    @patch('model.announcements.execute_query')
    def test_get_by_id(self, mock_query):
        mock_query.return_value = {
            'id': 5, 'title': 'T', 'content': 'C', 'images': None,
            'level': 'info', 'status': 'draft', 'created_by': 1,
        }
        entity = AnnouncementsModel.get_by_id(5)
        self.assertIsInstance(entity, AnnouncementEntity)
        self.assertEqual(entity.id, 5)

    @patch('model.announcements.execute_query')
    def test_get_by_id_not_found(self, mock_query):
        mock_query.return_value = None
        self.assertIsNone(AnnouncementsModel.get_by_id(999))

    @patch('model.announcements.execute_query')
    def test_list_for_user_joins_read_state(self, mock_query):
        mock_query.return_value = [
            {'id': 1, 'title': 'A', 'read_id': 11, 'images': None, 'status': 'published'},
            {'id': 2, 'title': 'B', 'read_id': None, 'images': None, 'status': 'published'},
        ]
        items = AnnouncementsModel.list_for_user(user_id=7)
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0].is_read)
        self.assertFalse(items[1].is_read)
        sql, params = mock_query.call_args.args
        # LEFT JOIN 已读表并按 user_id 过滤
        self.assertIn("LEFT JOIN announcement_reads", sql)
        self.assertIn("a.status = 'published'", sql)
        self.assertIn("a.publish_at IS NULL OR a.publish_at <= NOW()", sql)
        self.assertIn("a.expire_at IS NULL OR a.expire_at > NOW()", sql)
        self.assertEqual(params[0], 7)

    @patch('model.announcements.execute_query')
    def test_get_unread_count_for_user(self, mock_query):
        mock_query.return_value = {'cnt': 3}
        count = AnnouncementsModel.get_unread_count_for_user(7)
        self.assertEqual(count, 3)
        sql, params = mock_query.call_args.args
        self.assertIn("NOT EXISTS", sql)
        self.assertEqual(params, (7,))


class TestAnnouncementReadsModel(unittest.TestCase):
    """测试 AnnouncementReadsModel 数据操作（mock 数据库）"""

    @patch('model.announcement_reads.execute_update')
    def test_mark_read_insert_ignore(self, mock_update):
        mock_update.return_value = 1
        affected = AnnouncementReadsModel.mark_read(announcement_id=1, user_id=7)
        self.assertEqual(affected, 1)
        sql, params = mock_update.call_args.args
        self.assertIn("INSERT IGNORE INTO announcement_reads", sql)
        self.assertEqual(params, (1, 7))

    @patch('model.announcement_reads.execute_update')
    def test_mark_all_read_selects_active_published(self, mock_update):
        mock_update.return_value = 2
        affected = AnnouncementReadsModel.mark_all_read(user_id=7)
        self.assertEqual(affected, 2)
        sql, params = mock_update.call_args.args
        self.assertIn("INSERT IGNORE INTO announcement_reads", sql)
        self.assertIn("SELECT a.id, %s FROM announcements a", sql)
        self.assertIn("a.status = 'published'", sql)
        self.assertEqual(params, (7,))

    @patch('model.announcement_reads.execute_query')
    def test_list_read_ids_by_user(self, mock_query):
        mock_query.return_value = [{'announcement_id': 1}, {'announcement_id': 4}]
        ids = AnnouncementReadsModel.list_read_ids_by_user(7)
        self.assertEqual(ids, [1, 4])

    @patch('model.announcement_reads.execute_update')
    def test_delete_by_announcement(self, mock_update):
        mock_update.return_value = 5
        affected = AnnouncementReadsModel.delete_by_announcement(1)
        self.assertEqual(affected, 5)
        sql, params = mock_update.call_args.args
        self.assertIn("DELETE FROM announcement_reads WHERE announcement_id = %s", sql)
        self.assertEqual(params, (1,))


class TestAnnouncementReadEntity(unittest.TestCase):
    """测试 AnnouncementReadEntity 实体类"""

    def test_to_dict(self):
        read_at = datetime(2026, 9, 6, 12, 0, 0)
        entity = AnnouncementReadEntity(id=1, announcement_id=2, user_id=3, read_at=read_at)
        d = entity.to_dict()
        self.assertEqual(d['announcement_id'], 2)
        self.assertEqual(d['user_id'], 3)
        self.assertEqual(d['read_at'], read_at.isoformat())


if __name__ == '__main__':
    unittest.main()
