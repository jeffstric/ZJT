"""
World 表 CRUD 测试
"""
import unittest
from ..base.base_db_test import DatabaseTestCase


class TestWorldCRUD(DatabaseTestCase):
    """World 表增删改查测试"""
    
    def test_create_world(self):
        """测试创建世界"""
        world_id = self.insert_fixture('world', {
            'name': '科幻世界',
            'description': '一个充满科技的未来世界',
            'story_outline': '人类探索宇宙的故事',
            'visual_style': '赛博朋克风格',
            'era_environment': '2077年',
            'color_language': '蓝色和紫色为主',
            'composition_preference': '广角镜头',
            'user_id': 1
        })
        
        self.assertIsNotNone(world_id)
        self.assertGreater(world_id, 0)
    
    def test_read_world(self):
        """测试查询世界"""
        world_id = self.insert_fixture('world', {
            'name': '魔法世界',
            'description': '充满魔法的奇幻世界',
            'user_id': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `world` WHERE id = %s",
            (world_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], '魔法世界')
        self.assertEqual(result[0]['description'], '充满魔法的奇幻世界')
        self.assertEqual(result[0]['user_id'], 1)
    
    def test_update_world(self):
        """测试更新世界"""
        world_id = self.insert_fixture('world', {
            'name': '古代世界',
            'description': '古代文明',
            'user_id': 1
        })
        
        affected_rows = self.execute_update(
            "UPDATE `world` SET name = %s, description = %s WHERE id = %s",
            ('现代世界', '现代都市文明', world_id)
        )
        
        self.assertEqual(affected_rows, 1)
        
        result = self.execute_query(
            "SELECT * FROM `world` WHERE id = %s",
            (world_id,)
        )
        
        self.assertEqual(result[0]['name'], '现代世界')
        self.assertEqual(result[0]['description'], '现代都市文明')
    
    def test_delete_world(self):
        """测试删除世界"""
        world_id = self.insert_fixture('world', {
            'name': '临时世界',
            'user_id': 1
        })
        
        count_before = self.count_rows('world', 'id = %s', (world_id,))
        self.assertEqual(count_before, 1)
        
        affected_rows = self.execute_update(
            "DELETE FROM `world` WHERE id = %s",
            (world_id,)
        )
        
        self.assertEqual(affected_rows, 1)
        
        count_after = self.count_rows('world', 'id = %s', (world_id,))
        self.assertEqual(count_after, 0)
    
    def test_query_worlds_by_user(self):
        """测试按用户查询世界"""
        self.insert_fixture('world', {'name': '世界1', 'user_id': 1})
        self.insert_fixture('world', {'name': '世界2', 'user_id': 1})
        self.insert_fixture('world', {'name': '世界3', 'user_id': 2})
        
        result = self.execute_query(
            "SELECT * FROM `world` WHERE user_id = %s ORDER BY name",
            (1,)
        )
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], '世界1')
        self.assertEqual(result[1]['name'], '世界2')

    def test_soft_delete_and_restore_world(self):
        """测试世界伪删除与恢复"""
        world_id = self.insert_fixture('world', {
            'name': '可隐藏世界',
            'user_id': 1,
            'is_deleted': 0,
        })

        affected = self.execute_update(
            "UPDATE `world` SET is_deleted = 1, deleted_at = NOW() "
            "WHERE id = %s AND is_deleted = 0",
            (world_id,)
        )
        self.assertEqual(affected, 1)

        row = self.execute_query(
            "SELECT is_deleted, deleted_at FROM `world` WHERE id = %s",
            (world_id,)
        )
        self.assertEqual(len(row), 1)
        self.assertEqual(int(row[0]['is_deleted']), 1)
        self.assertIsNotNone(row[0]['deleted_at'])

        # 默认列表（未删除）不应包含
        active = self.execute_query(
            "SELECT id FROM `world` WHERE user_id = %s AND is_deleted = 0 AND id = %s",
            (1, world_id)
        )
        self.assertEqual(len(active), 0)

        # 已删除列表应包含
        deleted = self.execute_query(
            "SELECT id FROM `world` WHERE user_id = %s AND is_deleted = 1 AND id = %s",
            (1, world_id)
        )
        self.assertEqual(len(deleted), 1)

        # 恢复
        affected = self.execute_update(
            "UPDATE `world` SET is_deleted = 0, deleted_at = NULL "
            "WHERE id = %s AND is_deleted = 1",
            (world_id,)
        )
        self.assertEqual(affected, 1)

        row = self.execute_query(
            "SELECT is_deleted, deleted_at FROM `world` WHERE id = %s",
            (world_id,)
        )
        self.assertEqual(int(row[0]['is_deleted']), 0)
        self.assertIsNone(row[0]['deleted_at'])

    def test_get_by_name_skips_soft_deleted(self):
        """伪删除世界不占用名称（创建时可复用）"""
        self.insert_fixture('world', {
            'name': '同名世界',
            'user_id': 1,
            'is_deleted': 1,
        })

        # 仅查未删除时不应命中
        active = self.execute_query(
            "SELECT * FROM `world` WHERE user_id = %s AND name = %s AND is_deleted = 0",
            (1, '同名世界')
        )
        self.assertEqual(len(active), 0)

        # include_deleted 语义：全量可命中
        all_rows = self.execute_query(
            "SELECT * FROM `world` WHERE user_id = %s AND name = %s",
            (1, '同名世界')
        )
        self.assertEqual(len(all_rows), 1)


if __name__ == '__main__':
    unittest.main()
