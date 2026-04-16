"""
MediaFileMapping 表 CRUD 测试
"""
import unittest
from datetime import datetime
from ..base.base_db_test import DatabaseTestCase


class TestMediaFileMappingCRUD(DatabaseTestCase):
    """MediaFileMapping 表增删改查测试"""

    def test_create_media_file_mapping(self):
        """测试创建 media_file_mapping 记录"""
        mapping_id = self.insert_fixture('media_file_mapping', {
            'user_id': 1,
            'local_path': 'upload/medias/2026-04/123_20260407_abc123.mp4',
            'cloud_path': None,
            'policy_code': 'media_cache',
            'entity_type': 1,
            'source_id': 123,
            'media_type': 'video',
            'original_url': None,
            'file_size': 1024000,
            'status': 'active'
        })

        self.assertIsNotNone(mapping_id)
        self.assertGreater(mapping_id, 0)

    def test_get_by_local_path(self):
        """测试按 local_path 查询"""
        local_path = 'upload/medias/2026-04/test_456.jpg'
        self.insert_fixture('media_file_mapping', {
            'user_id': 1,
            'local_path': local_path,
            'cloud_path': None,
            'policy_code': 'media_cache',
            'entity_type': 1,
            'source_id': 456,
            'media_type': 'image',
            'status': 'active'
        })

        result = self.execute_query(
            "SELECT * FROM `media_file_mapping` WHERE local_path = %s",
            (local_path,)
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['local_path'], local_path)
        self.assertEqual(result[0]['media_type'], 'image')

    def test_update_cloud_path(self):
        """测试更新 cloud_path"""
        mapping_id = self.insert_fixture('media_file_mapping', {
            'user_id': 1,
            'local_path': 'upload/test_update.jpg',
            'cloud_path': None,
            'policy_code': 'media_cache',
            'entity_type': 0,
            'source_id': 1,
            'media_type': 'image',
            'status': 'active'
        })

        affected_rows = self.execute_update(
            "UPDATE `media_file_mapping` SET cloud_path = %s, status = %s WHERE id = %s",
            ('ai_tools/upload/test_update.jpg', 'active', mapping_id)
        )

        self.assertEqual(affected_rows, 1)

        result = self.execute_query(
            "SELECT * FROM `media_file_mapping` WHERE id = %s",
            (mapping_id,)
        )

        self.assertEqual(result[0]['cloud_path'], 'ai_tools/upload/test_update.jpg')

    def test_update_status(self):
        """测试更新状态"""
        mapping_id = self.insert_fixture('media_file_mapping', {
            'user_id': 1,
            'local_path': 'upload/test_status.jpg',
            'cloud_path': None,
            'policy_code': 'media_cache',
            'entity_type': 0,
            'source_id': 2,
            'media_type': 'image',
            'status': 'active'
        })

        affected_rows = self.execute_update(
            "UPDATE `media_file_mapping` SET status = %s WHERE local_path = %s",
            ('syncing', 'upload/test_status.jpg')
        )

        self.assertEqual(affected_rows, 1)

        result = self.execute_query(
            "SELECT status FROM `media_file_mapping` WHERE id = %s",
            (mapping_id,)
        )

        self.assertEqual(result[0]['status'], 'syncing')

    def test_delete_by_local_path(self):
        """测试按 local_path 删除"""
        local_path = 'upload/test_delete.jpg'
        self.insert_fixture('media_file_mapping', {
            'user_id': 1,
            'local_path': local_path,
            'cloud_path': None,
            'policy_code': 'media_cache',
            'entity_type': 0,
            'source_id': 3,
            'media_type': 'image',
            'status': 'active'
        })

        count_before = self.count_rows('media_file_mapping', 'local_path = %s', (local_path,))
        self.assertEqual(count_before, 1)

        affected_rows = self.execute_update(
            "DELETE FROM `media_file_mapping` WHERE local_path = %s",
            (local_path,)
        )

        self.assertEqual(affected_rows, 1)

        count_after = self.count_rows('media_file_mapping', 'local_path = %s', (local_path,))
        self.assertEqual(count_after, 0)

    def test_get_by_source(self):
        """测试按 entity_type 和 source_id 查询"""
        # 插入多条记录
        for i in range(3):
            self.insert_fixture('media_file_mapping', {
                'user_id': 1,
                'local_path': f'upload/test_source_{i}.jpg',
                'cloud_path': None,
                'policy_code': 'media_cache',
                'entity_type': 1,
                'source_id': 123 + i,
                'media_type': 'image',
                'status': 'active'
            })

        result = self.execute_query(
            "SELECT * FROM `media_file_mapping` WHERE entity_type = %s",
            (1,)
        )

        self.assertGreaterEqual(len(result), 3)

    def test_unique_constraint_on_entity_type_source_id(self):
        """测试 (entity_type, source_id) 唯一约束"""
        self.insert_fixture('media_file_mapping', {
            'user_id': 1,
            'local_path': 'upload/unique_test_1.jpg',
            'cloud_path': None,
            'policy_code': 'media_cache',
            'entity_type': 0,
            'source_id': 5,
            'media_type': 'image',
            'status': 'active'
        })

        # 尝试插入相同 (entity_type, source_id) 的记录，应该失败
        with self.assertRaises(Exception):
            self.insert_fixture('media_file_mapping', {
                'user_id': 2,
                'local_path': 'upload/unique_test_2.jpg',
                'cloud_path': None,
                'policy_code': 'media_cache',
                'entity_type': 0,
                'source_id': 5,
                'media_type': 'image',
                'status': 'active'
            })


if __name__ == '__main__':
    unittest.main()
