"""
Wan2.2 RunningHub 驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['runninghub_request'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.wan22_runninghub_v1_driver import Wan22RunninghubV1Driver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING

WAN22_IMAGE_TO_VIDEO_TYPE = 11


class TestWan22RunninghubWithDB(BaseVideoDriverTest):
    """Wan2.2 驱动数据库集成测试"""
    
    def setUp(self):
        super().setUp()
        self.driver = Wan22RunninghubV1Driver()
    
    def tearDown(self):
        pass
    
    def test_driver_initialization(self):
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'wan22_runninghub_v1')
        self.assertEqual(self.driver.driver_type, WAN22_IMAGE_TO_VIDEO_TYPE)
    
    @patch('task.video_drivers.wan22_runninghub_v1_driver.create_wan22_image_to_video')
    def test_submit_task_success(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=WAN22_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 Wan2.2 提交成功',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        mock_api.return_value = {"taskId": "wan22_task_123", "status": "QUEUED"}
        result = self.driver.submit_task(tool)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'wan22_task_123')
    
    @patch('task.video_drivers.wan22_runninghub_v1_driver.create_wan22_image_to_video')
    def test_submit_task_invalid_response(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=WAN22_IMAGE_TO_VIDEO_TYPE,
            prompt='测试响应格式错误',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        mock_api.return_value = {"errorCode": "INVALID"}
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
    
    @patch('task.video_drivers.wan22_runninghub_v1_driver.create_wan22_image_to_video')
    def test_submit_task_network_error(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=WAN22_IMAGE_TO_VIDEO_TYPE,
            prompt='测试网络错误',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        mock_api.side_effect = ConnectionError('Network timeout')
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])
    
    @patch('task.video_drivers.wan22_runninghub_v1_driver.check_ltx2_task_status')
    def test_check_status_success(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=WAN22_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查成功',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='wan22_task_456'
        )
        
        class MockResult:
            file_url = "https://example.com/result.mp4"
        
        mock_api.return_value = {"status": "SUCCESS", "results": [MockResult()]}
        result = self.driver.check_status('wan22_task_456')
        self.assertEqual(result['status'], 'SUCCESS')
    
    @patch('task.video_drivers.wan22_runninghub_v1_driver.check_ltx2_task_status')
    def test_check_status_failed(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=WAN22_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查失败',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='wan22_task_789'
        )
        
        mock_api.return_value = {"status": "FAILED"}
        result = self.driver.check_status('wan22_task_789')
        self.assertEqual(result['status'], 'FAILED')
    
    @patch('task.video_drivers.wan22_runninghub_v1_driver.check_ltx2_task_status')
    def test_check_status_processing(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=WAN22_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查处理中',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='wan22_task_999'
        )
        
        mock_api.return_value = {"status": "RUNNING"}
        result = self.driver.check_status('wan22_task_999')
        self.assertEqual(result['status'], 'RUNNING')


if __name__ == '__main__':
    import unittest
    unittest.main()
