"""
Location 表 CRUD 测试
"""
import unittest
from .base_db_test import DatabaseTestCase


class TestLocationCRUD(DatabaseTestCase):
    """Location 表增删改查测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.test_world_id = self.insert_fixture('world', {
            'name': '测试世界',
            'user_id': 1
        })
    
    def test_create_location(self):
        """测试创建地点"""
        location_id = self.insert_fixture('location', {
            'world_id': self.test_world_id,
            'name': '魔法学院',
            'description': '培养魔法师的学院',
            'reference_image': 'https://example.com/academy.jpg',
            'user_id': 1
        })
        
        self.assertIsNotNone(location_id)
        self.assertGreater(location_id, 0)
    
    def test_read_location(self):
        """测试查询地点"""
        location_id = self.insert_fixture('location', {
            'world_id': self.test_world_id,
            'name': '黑暗森林',
            'description': '危险的森林区域',
            'user_id': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `location` WHERE id = %s",
            (location_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], '黑暗森林')
        self.assertEqual(result[0]['description'], '危险的森林区域')
    
    def test_update_location(self):
        """测试更新地点"""
        location_id = self.insert_fixture('location', {
            'world_id': self.test_world_id,
            'name': '旧城堡',
            'user_id': 1
        })
        
        affected_rows = self.execute_update(
            "UPDATE `location` SET name = %s, description = %s WHERE id = %s",
            ('新城堡', '翻新后的城堡', location_id)
        )
        
        self.assertEqual(affected_rows, 1)
        
        result = self.execute_query(
            "SELECT * FROM `location` WHERE id = %s",
            (location_id,)
        )
        
        self.assertEqual(result[0]['name'], '新城堡')
        self.assertEqual(result[0]['description'], '翻新后的城堡')
    
    def test_delete_location(self):
        """测试删除地点"""
        location_id = self.insert_fixture('location', {
            'world_id': self.test_world_id,
            'name': '临时地点',
            'user_id': 1
        })
        
        count_before = self.count_rows('location', 'id = %s', (location_id,))
        self.assertEqual(count_before, 1)
        
        affected_rows = self.execute_update(
            "DELETE FROM `location` WHERE id = %s",
            (location_id,)
        )
        
        self.assertEqual(affected_rows, 1)
        
        count_after = self.count_rows('location', 'id = %s', (location_id,))
        self.assertEqual(count_after, 0)
    
    def test_parent_child_location(self):
        """测试父子地点关系"""
        parent_id = self.insert_fixture('location', {
            'world_id': self.test_world_id,
            'name': '王国',
            'user_id': 1
        })
        
        child_id = self.insert_fixture('location', {
            'world_id': self.test_world_id,
            'name': '王宫',
            'parent_id': parent_id,
            'user_id': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `location` WHERE parent_id = %s",
            (parent_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], '王宫')
        self.assertEqual(result[0]['parent_id'], parent_id)


if __name__ == '__main__':
    unittest.main()
