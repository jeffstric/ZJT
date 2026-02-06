"""
Props 表 CRUD 测试
"""
import unittest
from .base_db_test import DatabaseTestCase


class TestPropsCRUD(DatabaseTestCase):
    """Props 表增删改查测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.test_world_id = self.insert_fixture('world', {
            'name': '测试世界',
            'user_id': 1
        })
    
    def test_create_props(self):
        """测试创建道具"""
        props_id = self.insert_fixture('props', {
            'world_id': self.test_world_id,
            'name': '魔法杖',
            'content': '强大的魔法道具',
            'reference_image': 'https://example.com/wand.jpg',
            'other_info': '由古老的木材制成',
            'user_id': 1
        })
        
        self.assertIsNotNone(props_id)
        self.assertGreater(props_id, 0)
    
    def test_read_props(self):
        """测试查询道具"""
        props_id = self.insert_fixture('props', {
            'world_id': self.test_world_id,
            'name': '圣剑',
            'content': '传说中的神器',
            'user_id': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `props` WHERE id = %s",
            (props_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], '圣剑')
        self.assertEqual(result[0]['content'], '传说中的神器')
    
    def test_update_props(self):
        """测试更新道具"""
        props_id = self.insert_fixture('props', {
            'world_id': self.test_world_id,
            'name': '普通剑',
            'content': '普通的武器',
            'user_id': 1
        })
        
        affected_rows = self.execute_update(
            "UPDATE `props` SET name = %s, content = %s WHERE id = %s",
            ('神剑', '经过强化的武器', props_id)
        )
        
        self.assertEqual(affected_rows, 1)
        
        result = self.execute_query(
            "SELECT * FROM `props` WHERE id = %s",
            (props_id,)
        )
        
        self.assertEqual(result[0]['name'], '神剑')
        self.assertEqual(result[0]['content'], '经过强化的武器')
    
    def test_delete_props(self):
        """测试删除道具"""
        props_id = self.insert_fixture('props', {
            'world_id': self.test_world_id,
            'name': '临时道具',
            'user_id': 1
        })
        
        count_before = self.count_rows('props', 'id = %s', (props_id,))
        self.assertEqual(count_before, 1)
        
        affected_rows = self.execute_update(
            "DELETE FROM `props` WHERE id = %s",
            (props_id,)
        )
        
        self.assertEqual(affected_rows, 1)
        
        count_after = self.count_rows('props', 'id = %s', (props_id,))
        self.assertEqual(count_after, 0)
    
    def test_query_props_by_world(self):
        """测试按世界查询道具"""
        self.insert_fixture('props', {
            'world_id': self.test_world_id,
            'name': '道具1',
            'user_id': 1
        })
        self.insert_fixture('props', {
            'world_id': self.test_world_id,
            'name': '道具2',
            'user_id': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `props` WHERE world_id = %s ORDER BY name",
            (self.test_world_id,)
        )
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], '道具1')
        self.assertEqual(result[1]['name'], '道具2')


if __name__ == '__main__':
    unittest.main()
