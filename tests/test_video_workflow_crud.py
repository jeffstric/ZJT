"""
VideoWorkflow 表 CRUD 测试
"""
import unittest
import json
from .base_db_test import DatabaseTestCase


class TestVideoWorkflowCRUD(DatabaseTestCase):
    """VideoWorkflow 表增删改查测试"""
    
    def test_create_video_workflow(self):
        """测试创建视频工作流"""
        workflow_data = {
            'nodes': ['node1', 'node2'],
            'connections': [{'from': 'node1', 'to': 'node2'}]
        }
        
        workflow_id = self.insert_fixture('video_workflow', {
            'name': '标准工作流',
            'description': '用于生成标准视频的工作流',
            'cover_image': 'https://example.com/cover.jpg',
            'user_id': 1,
            'status': 1,
            'style': '写实风格'
        })
        
        self.execute_update(
            "UPDATE `video_workflow` SET workflow_data = %s WHERE id = %s",
            (json.dumps(workflow_data), workflow_id)
        )
        
        self.assertIsNotNone(workflow_id)
        self.assertGreater(workflow_id, 0)
    
    def test_read_video_workflow(self):
        """测试查询视频工作流"""
        workflow_id = self.insert_fixture('video_workflow', {
            'name': '动画工作流',
            'description': '用于生成动画的工作流',
            'user_id': 1,
            'status': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `video_workflow` WHERE id = %s",
            (workflow_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], '动画工作流')
        self.assertEqual(result[0]['status'], 1)
    
    def test_update_video_workflow(self):
        """测试更新视频工作流"""
        workflow_id = self.insert_fixture('video_workflow', {
            'name': '草稿工作流',
            'user_id': 1,
            'status': 2
        })
        
        affected_rows = self.execute_update(
            "UPDATE `video_workflow` SET name = %s, status = %s WHERE id = %s",
            ('正式工作流', 1, workflow_id)
        )
        
        self.assertEqual(affected_rows, 1)
        
        result = self.execute_query(
            "SELECT * FROM `video_workflow` WHERE id = %s",
            (workflow_id,)
        )
        
        self.assertEqual(result[0]['name'], '正式工作流')
        self.assertEqual(result[0]['status'], 1)
    
    def test_delete_video_workflow(self):
        """测试删除视频工作流"""
        workflow_id = self.insert_fixture('video_workflow', {
            'name': '临时工作流',
            'user_id': 1,
            'status': 2
        })
        
        count_before = self.count_rows('video_workflow', 'id = %s', (workflow_id,))
        self.assertEqual(count_before, 1)
        
        affected_rows = self.execute_update(
            "DELETE FROM `video_workflow` WHERE id = %s",
            (workflow_id,)
        )
        
        self.assertEqual(affected_rows, 1)
        
        count_after = self.count_rows('video_workflow', 'id = %s', (workflow_id,))
        self.assertEqual(count_after, 0)
    
    def test_query_workflows_by_status(self):
        """测试按状态查询工作流"""
        self.insert_fixture('video_workflow', {
            'name': '启用工作流1',
            'user_id': 1,
            'status': 1
        })
        self.insert_fixture('video_workflow', {
            'name': '启用工作流2',
            'user_id': 1,
            'status': 1
        })
        self.insert_fixture('video_workflow', {
            'name': '草稿工作流',
            'user_id': 1,
            'status': 2
        })
        
        result = self.execute_query(
            "SELECT * FROM `video_workflow` WHERE status = %s ORDER BY name",
            (1,)
        )
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['status'], 1)
        self.assertEqual(result[1]['status'], 1)
    
    def test_workflow_with_json_data(self):
        """测试工作流 JSON 数据"""
        workflow_data = {
            'version': '1.0',
            'nodes': [
                {'id': 1, 'type': 'input'},
                {'id': 2, 'type': 'process'},
                {'id': 3, 'type': 'output'}
            ]
        }
        
        workflow_id = self.insert_fixture('video_workflow', {
            'name': 'JSON测试工作流',
            'user_id': 1,
            'status': 1
        })
        
        self.execute_update(
            "UPDATE `video_workflow` SET workflow_data = %s WHERE id = %s",
            (json.dumps(workflow_data), workflow_id)
        )
        
        result = self.execute_query(
            "SELECT workflow_data FROM `video_workflow` WHERE id = %s",
            (workflow_id,)
        )
        
        loaded_data = result[0]['workflow_data']
        if isinstance(loaded_data, str):
            loaded_data = json.loads(loaded_data)
        
        self.assertIsInstance(loaded_data, dict)
        self.assertEqual(loaded_data['version'], '1.0')
        self.assertEqual(len(loaded_data['nodes']), 3)


if __name__ == '__main__':
    unittest.main()
