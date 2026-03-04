"""
AITools 表 CRUD 测试
"""
import unittest
from datetime import datetime
from .base_db_test import DatabaseTestCase


class TestAIToolsCRUD(DatabaseTestCase):
    """AITools 表增删改查测试"""
    
    def test_create_ai_tool(self):
        """测试创建 AI 工具记录"""
        tool_id = self.insert_fixture('ai_tools', {
            'prompt': '生成一个科幻场景',
            'image_path': 'https://example.com/image.jpg',
            'duration': 5,
            'ratio': '16:9',
            'project_id': 'proj_123',
            'user_id': 1,
            'type': 2,
            'status': 0
        })
        
        self.assertIsNotNone(tool_id)
        self.assertGreater(tool_id, 0)
    
    def test_read_ai_tool(self):
        """测试查询 AI 工具记录"""
        tool_id = self.insert_fixture('ai_tools', {
            'prompt': '生成魔法效果',
            'type': 3,
            'status': 1,
            'user_id': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s",
            (tool_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['prompt'], '生成魔法效果')
        self.assertEqual(result[0]['type'], 3)
        self.assertEqual(result[0]['status'], 1)
    
    def test_update_ai_tool(self):
        """测试更新 AI 工具记录"""
        tool_id = self.insert_fixture('ai_tools', {
            'prompt': '初始提示词',
            'type': 2,
            'status': 0,
            'user_id': 1
        })
        
        affected_rows = self.execute_update(
            "UPDATE `ai_tools` SET status = %s, result_url = %s WHERE id = %s",
            (2, 'https://example.com/result.mp4', tool_id)
        )
        
        self.assertEqual(affected_rows, 1)
        
        result = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s",
            (tool_id,)
        )
        
        self.assertEqual(result[0]['status'], 2)
        self.assertEqual(result[0]['result_url'], 'https://example.com/result.mp4')
    
    def test_delete_ai_tool(self):
        """测试删除 AI 工具记录"""
        tool_id = self.insert_fixture('ai_tools', {
            'prompt': '临时任务',
            'type': 1,
            'status': -1,
            'user_id': 1
        })
        
        count_before = self.count_rows('ai_tools', 'id = %s', (tool_id,))
        self.assertEqual(count_before, 1)
        
        affected_rows = self.execute_update(
            "DELETE FROM `ai_tools` WHERE id = %s",
            (tool_id,)
        )
        
        self.assertEqual(affected_rows, 1)
        
        count_after = self.count_rows('ai_tools', 'id = %s', (tool_id,))
        self.assertEqual(count_after, 0)
    
    def test_query_tools_by_user_and_type(self):
        """测试按用户和类型查询工具"""
        self.insert_fixture('ai_tools', {
            'prompt': '视频任务1',
            'user_id': 1,
            'type': 2,
            'status': 0
        })
        self.insert_fixture('ai_tools', {
            'prompt': '视频任务2',
            'user_id': 1,
            'type': 2,
            'status': 1
        })
        self.insert_fixture('ai_tools', {
            'prompt': '图片任务',
            'user_id': 1,
            'type': 1,
            'status': 0
        })
        
        result = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE user_id = %s AND type = %s",
            (1, 2)
        )
        
        self.assertEqual(len(result), 2)
        for row in result:
            self.assertEqual(row['type'], 2)
    
    def test_query_tools_by_status(self):
        """测试按状态查询工具"""
        self.insert_fixture('ai_tools', {
            'prompt': '处理中任务1',
            'user_id': 1,
            'type': 2,
            'status': 1
        })
        self.insert_fixture('ai_tools', {
            'prompt': '处理中任务2',
            'user_id': 1,
            'type': 2,
            'status': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE status = %s",
            (1,)
        )
        
        self.assertGreaterEqual(len(result), 2)
        for row in result:
            self.assertEqual(row['status'], 1)


if __name__ == '__main__':
    unittest.main()
