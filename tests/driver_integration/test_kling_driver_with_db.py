"""
Kling Duomi 驱动数据库集成测试
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['duomi_api_requset'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.kling_duomi_v1_driver import KlingDuomiV1Driver


class TestKlingDriverWithDB(BaseVideoDriverTest):
    """Kling 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = KlingDuomiV1Driver()
        
        self.test_ai_tool_id = self.create_test_ai_tool(
            ai_tool_type=12,
            prompt='生成动态视频',
            image_path='https://example.com/kling_image.jpg',
            duration=5
        )
    
    @patch('task.video_drivers.kling_duomi_v1_driver.create_kling_image_to_video')
    def test_submit_task_success(self, mock_create_video):
        """测试成功提交 Kling 任务"""
        mock_create_video.return_value = {
            'code': 0,
            'data': {
                'task_id': 'kling_task_12345'
            }
        }
        
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        result = self.driver.submit_task(ai_tool)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'kling_task_12345')
    
    @patch('task.video_drivers.kling_duomi_v1_driver.create_kling_image_to_video')
    def test_submit_task_api_error(self, mock_create_video):
        """测试 API 返回错误"""
        mock_create_video.return_value = {
            'code': 1001,
            'message': 'Invalid parameters'
        }
        
        ai_tool = self.get_ai_tool_from_db(self.test_ai_tool_id)
        result = self.driver.submit_task(ai_tool)
        
        self.assertFalse(result['success'])
        self.assertIn('error', result)
    
    @patch('task.video_drivers.kling_duomi_v1_driver.get_kling_task_status')
    def test_check_status_success(self, mock_get_status):
        """测试检查任务状态 - 成功"""
        mock_get_status.return_value = {
            'code': 0,
            'data': {
                'task_status': 'succeed',
                'task_result': {
                    'videos': [
                        {'url': 'https://example.com/kling_result.mp4'}
                    ]
                }
            }
        }
        
        result = self.driver.check_status('kling_task_12345')
        
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/kling_result.mp4')
    
    @patch('task.video_drivers.kling_duomi_v1_driver.get_kling_task_status')
    def test_check_status_processing(self, mock_get_status):
        """测试检查任务状态 - 处理中"""
        mock_get_status.return_value = {
            'code': 0,
            'data': {
                'task_status': 'processing'
            }
        }
        
        result = self.driver.check_status('kling_task_12345')
        
        self.assertEqual(result['status'], 'RUNNING')
    
    @patch('task.video_drivers.kling_duomi_v1_driver.get_kling_task_status')
    def test_check_status_failed(self, mock_get_status):
        """测试检查任务状态 - 失败"""
        mock_get_status.return_value = {
            'code': 0,
            'data': {
                'task_status': 'failed'
            }
        }
        
        result = self.driver.check_status('kling_task_12345')
        
        self.assertEqual(result['status'], 'FAILED')
    
    def test_update_kling_task_with_project_id(self):
        """测试更新 Kling 任务的 project_id"""
        project_id = 'kling_proj_test_123'
        
        self.update_ai_tool_status(
            self.test_ai_tool_id,
            status=1,
            project_id=project_id
        )
        
        result_project_id = self.assert_ai_tool_has_project_id(self.test_ai_tool_id)
        self.assertEqual(result_project_id, project_id)


if __name__ == '__main__':
    import unittest
    unittest.main()
