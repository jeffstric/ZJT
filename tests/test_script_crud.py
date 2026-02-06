"""
Script 表 CRUD 测试
"""
import unittest
from .base_db_test import DatabaseTestCase


class TestScriptCRUD(DatabaseTestCase):
    """Script 表增删改查测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.test_world_id = self.insert_fixture('world', {
            'name': '测试世界',
            'user_id': 1
        })
    
    def test_create_script(self):
        """测试创建剧本"""
        script_id = self.insert_fixture('script', {
            'world_id': self.test_world_id,
            'user_id': 1,
            'title': '第一集：开端',
            'episode_number': 1,
            'content': '故事从一个平凡的早晨开始...'
        })
        
        self.assertIsNotNone(script_id)
        self.assertGreater(script_id, 0)
    
    def test_read_script(self):
        """测试查询剧本"""
        script_id = self.insert_fixture('script', {
            'world_id': self.test_world_id,
            'user_id': 1,
            'title': '第二集：冒险',
            'episode_number': 2,
            'content': '主角踏上了冒险之旅...'
        })
        
        result = self.execute_query(
            "SELECT * FROM `script` WHERE id = %s",
            (script_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['title'], '第二集：冒险')
        self.assertEqual(result[0]['episode_number'], 2)
        self.assertEqual(result[0]['content'], '主角踏上了冒险之旅...')
    
    def test_update_script(self):
        """测试更新剧本"""
        script_id = self.insert_fixture('script', {
            'world_id': self.test_world_id,
            'user_id': 1,
            'title': '草稿',
            'content': '待完善的内容'
        })
        
        affected_rows = self.execute_update(
            "UPDATE `script` SET title = %s, content = %s WHERE id = %s",
            ('第三集：转折', '故事迎来重大转折...', script_id)
        )
        
        self.assertEqual(affected_rows, 1)
        
        result = self.execute_query(
            "SELECT * FROM `script` WHERE id = %s",
            (script_id,)
        )
        
        self.assertEqual(result[0]['title'], '第三集：转折')
        self.assertEqual(result[0]['content'], '故事迎来重大转折...')
    
    def test_delete_script(self):
        """测试删除剧本"""
        script_id = self.insert_fixture('script', {
            'world_id': self.test_world_id,
            'user_id': 1,
            'title': '临时剧本'
        })
        
        count_before = self.count_rows('script', 'id = %s', (script_id,))
        self.assertEqual(count_before, 1)
        
        affected_rows = self.execute_update(
            "DELETE FROM `script` WHERE id = %s",
            (script_id,)
        )
        
        self.assertEqual(affected_rows, 1)
        
        count_after = self.count_rows('script', 'id = %s', (script_id,))
        self.assertEqual(count_after, 0)
    
    def test_query_scripts_by_episode(self):
        """测试按集数查询剧本"""
        self.insert_fixture('script', {
            'world_id': self.test_world_id,
            'user_id': 1,
            'title': '第1集',
            'episode_number': 1
        })
        self.insert_fixture('script', {
            'world_id': self.test_world_id,
            'user_id': 1,
            'title': '第2集',
            'episode_number': 2
        })
        
        result = self.execute_query(
            "SELECT * FROM `script` WHERE world_id = %s ORDER BY episode_number",
            (self.test_world_id,)
        )
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['episode_number'], 1)
        self.assertEqual(result[1]['episode_number'], 2)


if __name__ == '__main__':
    unittest.main()
