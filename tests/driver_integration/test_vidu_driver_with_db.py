"""
Vidu 驱动数据库集成测试
使用真实数据库测试驱动的提交和状态查询功能
"""
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.modules['vidu_api_requset'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.vidu_default_driver import ViduDefaultDriver


class TestViduDriverWithDB(BaseVideoDriverTest):
    """Vidu 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = ViduDefaultDriver()
        
        self.test_ai_tool_id = self.create_test_ai_tool(
            ai_tool_type=14,
            prompt='生成一个科幻场景的视频',
            image_path='https://example.com/test_image.jpg',
            duration=5,
            ratio='16:9'
        )
    
    @patch('task.video_drivers.vidu_default_driver.create_vidu_image_to_video')
    def test_submit_task_success(self, mock_create_video):
        """测试成功提交任务"""
        mock_create_video.return_value = {
            'task_id': 'vidu_task_12345',
            'state': 'created'
        }
        
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        result = self.driver.submit_task(ai_tool)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'vidu_task_12345')
        
        mock_create_video.assert_called_once()
        call_kwargs = mock_create_video.call_args[1]
        self.assertEqual(call_kwargs['image_url'], 'https://example.com/test_image.jpg')
        self.assertEqual(call_kwargs['prompt'], '生成一个科幻场景的视频')
        self.assertEqual(call_kwargs['duration'], 5)
    
    @patch('task.video_drivers.vidu_default_driver.create_vidu_image_to_video')
    def test_submit_task_api_error(self, mock_create_video):
        """测试 API 返回错误"""
        mock_create_video.return_value = {
            'error': 'Invalid image format'
        }
        
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        result = self.driver.submit_task(ai_tool)
        
        self.assertFalse(result['success'])
        self.assertIn('error', result)
    
    @patch('task.video_drivers.vidu_default_driver.create_vidu_start_end_to_video')
    def test_submit_task_with_two_images(self, mock_create_video):
        """测试提交双图任务（首尾图生视频）"""
        self.execute_update(
            "UPDATE `ai_tools` SET image_path = %s WHERE id = %s",
            ('https://example.com/start.jpg,https://example.com/end.jpg', self.test_ai_tool_id)
        )
        
        mock_create_video.return_value = {
            'task_id': 'vidu_task_67890',
            'state': 'created'
        }
        
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        result = self.driver.submit_task(ai_tool)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'vidu_task_67890')
        
        mock_create_video.assert_called_once()
        call_kwargs = mock_create_video.call_args[1]
        self.assertEqual(call_kwargs['start_image_url'], 'https://example.com/start.jpg')
        self.assertEqual(call_kwargs['end_image_url'], 'https://example.com/end.jpg')
    
    @patch('task.video_drivers.vidu_default_driver.get_vidu_task_status')
    def test_check_status_success(self, mock_get_status):
        """测试检查任务状态 - 成功"""
        mock_get_status.return_value = {
            'id': 'vidu_task_12345',
            'state': 'success',
            'creations': [
                {'url': 'https://example.com/result_video.mp4'}
            ]
        }
        
        result = self.driver.check_status('vidu_task_12345')
        
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result_video.mp4')
    
    @patch('task.video_drivers.vidu_default_driver.get_vidu_task_status')
    def test_check_status_processing(self, mock_get_status):
        """测试检查任务状态 - 处理中"""
        mock_get_status.return_value = {
            'id': 'vidu_task_12345',
            'state': 'processing',
            'creations': []
        }
        
        result = self.driver.check_status('vidu_task_12345')
        
        self.assertEqual(result['status'], 'RUNNING')
        self.assertIn('message', result)
    
    @patch('task.video_drivers.vidu_default_driver.get_vidu_task_status')
    def test_check_status_failed(self, mock_get_status):
        """测试检查任务状态 - 失败"""
        mock_get_status.return_value = {
            'id': 'vidu_task_12345',
            'state': 'failed',
            'err_code': 'INVALID_IMAGE'
        }
        
        result = self.driver.check_status('vidu_task_12345')
        
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('error', result)
    
    @patch('task.video_drivers.vidu_default_driver.create_vidu_image_to_video')
    def test_full_workflow_with_db(self, mock_create_video):
        """测试完整工作流：创建任务 -> 更新数据库 -> 查询状态"""
        mock_create_video.return_value = {
            'task_id': 'vidu_workflow_test',
            'state': 'created'
        }
        
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        submit_result = self.driver.submit_task(ai_tool)
        
        self.assertTrue(submit_result['success'])
        project_id = submit_result['project_id']
        
        self.execute_update(
            "UPDATE `ai_tools` SET project_id = %s, status = %s WHERE id = %s",
            (project_id, 1, self.test_ai_tool_id)
        )
        
        updated_tool = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s",
            (self.test_ai_tool_id,)
        )
        
        self.assertEqual(updated_tool[0]['project_id'], project_id)
        self.assertEqual(updated_tool[0]['status'], 1)
    
    def test_query_ai_tool_by_status(self):
        """测试按状态查询 AI 工具"""
        self.insert_fixture('ai_tools', {
            'prompt': '测试任务1',
            'user_id': 1001,
            'type': 14,
            'status': 0
        })
        self.insert_fixture('ai_tools', {
            'prompt': '测试任务2',
            'user_id': 1001,
            'type': 14,
            'status': 1
        })
        
        pending_tasks = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE type = %s AND status = %s",
            (14, 0)
        )
        
        self.assertGreaterEqual(len(pending_tasks), 2)
    
    def test_update_task_result(self):
        """测试更新任务结果"""
        result_url = 'https://example.com/final_video.mp4'
        
        self.execute_update(
            "UPDATE `ai_tools` SET status = %s, result_url = %s WHERE id = %s",
            (2, result_url, self.test_ai_tool_id)
        )
        
        updated_tool = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s",
            (self.test_ai_tool_id,)
        )
        
        self.assertEqual(updated_tool[0]['status'], 2)
        self.assertEqual(updated_tool[0]['result_url'], result_url)


if __name__ == '__main__':
    unittest.main()
