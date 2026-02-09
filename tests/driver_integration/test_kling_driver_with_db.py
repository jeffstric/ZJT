"""
Kling Duomi 驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['duomi_api_requset'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.kling_duomi_v1_driver import KlingDuomiV1Driver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING

KLING_IMAGE_TO_VIDEO_TYPE = 12


class TestKlingDuomiWithDB(BaseVideoDriverTest):
    """Kling 驱动数据库集成测试"""
    
    def setUp(self):
        super().setUp()
        self.driver = KlingDuomiV1Driver()
    
    def tearDown(self):
        pass
    
    def test_driver_initialization(self):
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'kling_duomi_v1')
        self.assertEqual(self.driver.driver_type, KLING_IMAGE_TO_VIDEO_TYPE)
    
    @patch('task.video_drivers.kling_duomi_v1_driver.create_kling_image_to_video')
    def test_submit_task_success(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=KLING_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 Kling 提交成功',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        mock_api.return_value = {
            "code": 0,
            "data": {"task_id": "kling_task_123"}
        }
        result = self.driver.submit_task(tool)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'kling_task_123')
    
    @patch('task.video_drivers.kling_duomi_v1_driver.create_kling_image_to_video')
    def test_submit_task_invalid_response(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=KLING_IMAGE_TO_VIDEO_TYPE,
            prompt='测试响应格式错误',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        mock_api.return_value = {"error": "invalid"}
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
    
    @patch('task.video_drivers.kling_duomi_v1_driver.create_kling_image_to_video')
    def test_submit_task_network_error(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=KLING_IMAGE_TO_VIDEO_TYPE,
            prompt='测试网络错误',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        mock_api.side_effect = ConnectionError('Network timeout')
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])
    
    @patch('task.video_drivers.kling_duomi_v1_driver.get_kling_task_status')
    def test_check_status_success(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=KLING_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查成功',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='kling_task_456'
        )
        
        mock_api.return_value = {
            "code": 0,
            "data": {
                "task_status": "succeed",
                "task_result": {"videos": [{"url": "https://example.com/result.mp4"}]}
            }
        }
        
        result = self.driver.check_status('kling_task_456')
        self.assertEqual(result['status'], 'SUCCESS')
    
    @patch('task.video_drivers.kling_duomi_v1_driver.get_kling_task_status')
    def test_check_status_failed(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=KLING_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查失败',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='kling_task_789'
        )
        
        mock_api.return_value = {
            "code": 0,
            "data": {"task_status": "failed"}
        }
        
        result = self.driver.check_status('kling_task_789')
        self.assertEqual(result['status'], 'FAILED')
    
    @patch('task.video_drivers.kling_duomi_v1_driver.get_kling_task_status')
    def test_check_status_processing(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=KLING_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查处理中',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='kling_task_999'
        )
        
        mock_api.return_value = {
            "code": 0,
            "data": {"task_status": "processing"}
        }
        
        result = self.driver.check_status('kling_task_999')
        self.assertEqual(result['status'], 'RUNNING')


if __name__ == '__main__':
    import unittest
    unittest.main()
