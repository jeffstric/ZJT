"""
Vidu 驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['vidu_api_requset'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.vidu_default_driver import ViduDefaultDriver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING

VIDU_IMAGE_TO_VIDEO_TYPE = 14


class TestViduDefaultWithDB(BaseVideoDriverTest):
    """Vidu 驱动数据库集成测试"""
    
    def setUp(self):
        super().setUp()
        self.driver = ViduDefaultDriver()
    
    def tearDown(self):
        pass
    
    def test_driver_initialization(self):
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'vidu_default')
        self.assertEqual(self.driver.driver_type, VIDU_IMAGE_TO_VIDEO_TYPE)
    
    @patch('task.video_drivers.vidu_default_driver.create_vidu_image_to_video')
    def test_submit_task_success(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 Vidu 提交成功',
            image_path='https://example.com/test.jpg',
            duration=4,
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        # Vidu API返回格式：直接返回 {"task_id": "xxx", "state": "created"}
        mock_api.return_value = {
            "task_id": "vidu_task_123",
            "state": "created",
            "model": "Vidu3.1-图生视频-720p",
            "credits": 4
        }
        
        result = self.driver.submit_task(tool)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'vidu_task_123')
    
    @patch('task.video_drivers.vidu_default_driver.create_vidu_image_to_video')
    def test_submit_task_invalid_response(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试响应格式错误',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        # API返回业务错误
        mock_api.return_value = {"error": "invalid request"}
        
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
    
    @patch('task.video_drivers.vidu_default_driver.create_vidu_image_to_video')
    def test_submit_task_network_error(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试网络错误',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        mock_api.side_effect = ConnectionError('Network timeout')
        
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])
    
    @patch('task.video_drivers.vidu_default_driver.get_vidu_task_status')
    def test_check_status_success(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查成功',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='vidu_task_456'
        )
        
        # Vidu check_status 返回格式：{"id": "xxx", "state": "success", "creations": [{"url": "..."}]}
        mock_api.return_value = {
            "id": "vidu_task_456",
            "state": "success",
            "creations": [{"url": "https://example.com/result.mp4"}],
            "credits": 4
        }
        
        result = self.driver.check_status('vidu_task_456')
        
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result.mp4')
    
    @patch('task.video_drivers.vidu_default_driver.get_vidu_task_status')
    def test_check_status_failed(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查失败',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='vidu_task_789'
        )
        
        mock_api.return_value = {
            "id": "vidu_task_789",
            "state": "failed",
            "creations": [],
            "err_code": "CONTENT_VIOLATION"
        }
        
        result = self.driver.check_status('vidu_task_789')
        
        self.assertEqual(result['status'], 'FAILED')
    
    @patch('task.video_drivers.vidu_default_driver.get_vidu_task_status')
    def test_check_status_processing(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查处理中',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='vidu_task_999'
        )
        
        mock_api.return_value = {
            "id": "vidu_task_999",
            "state": "processing",
            "creations": []
        }
        
        result = self.driver.check_status('vidu_task_999')
        
        self.assertEqual(result['status'], 'RUNNING')


if __name__ == '__main__':
    import unittest
    unittest.main()
