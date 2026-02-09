"""
Sora2 Duomi 驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['duomi_api_requset'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.sora2_duomi_v1_driver import Sora2DuomiV1Driver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING

# Sora2 图生视频的任务类型
SORA2_IMAGE_TO_VIDEO_TYPE = 3


class TestSora2DriverWithDB(BaseVideoDriverTest):
    """Sora2 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = Sora2DuomiV1Driver()
    
    def tearDown(self):
        """测试结束后：不做任何操作，让基类处理事务回滚"""
        pass
    
    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'sora2_duomi_v1')
        self.assertEqual(self.driver.driver_type, SORA2_IMAGE_TO_VIDEO_TYPE)
    
    @patch('task.video_drivers.sora2_duomi_v1_driver.create_image_to_video')
    def test_submit_task_success(self, mock_api):
        """测试提交任务 - 成功"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=SORA2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 Sora2 提交成功',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.status, AI_TOOL_STATUS_PENDING)
        
        # Mock API返回正确格式：直接返回包含id的字典
        mock_api.return_value = {"id": "sora2_task_123"}
        
        result = self.driver.submit_task(tool)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'sora2_task_123')
    
    @patch('task.video_drivers.sora2_duomi_v1_driver.create_image_to_video')
    def test_submit_task_invalid_response(self, mock_api):
        """测试提交任务 - 响应格式错误"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=SORA2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试响应格式错误',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        # Mock API返回格式错误的响应
        mock_api.return_value = {"error": "invalid"}
        
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'SYSTEM')
        self.assertFalse(result['retry'])
    
    @patch('task.video_drivers.sora2_duomi_v1_driver.create_image_to_video')
    def test_submit_task_network_error(self, mock_api):
        """测试提交任务 - 网络错误"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=SORA2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试网络错误',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        # Mock 网络超时异常
        mock_api.side_effect = ConnectionError('Network timeout')
        
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])
    
    @patch('task.video_drivers.sora2_duomi_v1_driver.get_ai_task_result')
    def test_check_status_success(self, mock_api):
        """测试检查状态 - 成功"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=SORA2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查成功',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='sora2_task_456'
        )
        
        # Mock API返回成功状态（status=1表示成功）
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "status": 1,
                "mediaUrl": "https://example.com/result.mp4"
            }
        }
        
        result = self.driver.check_status('sora2_task_456')
        
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result.mp4')
    
    @patch('task.video_drivers.sora2_duomi_v1_driver.get_ai_task_result')
    def test_check_status_failed(self, mock_api):
        """测试检查状态 - 失败"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=SORA2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查失败',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='sora2_task_789'
        )
        
        # Mock API返回失败状态（status=2表示失败）
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "status": 2,
                "reason": "内容违规"
            }
        }
        
        result = self.driver.check_status('sora2_task_789')
        
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('error', result)
    
    @patch('task.video_drivers.sora2_duomi_v1_driver.get_ai_task_result')
    def test_check_status_processing(self, mock_api):
        """测试检查状态 - 处理中"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=SORA2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查处理中',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='sora2_task_999'
        )
        
        # Mock API返回处理中状态（status=0表示处理中）
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "status": 0
            }
        }
        
        result = self.driver.check_status('sora2_task_999')
        
        self.assertEqual(result['status'], 'RUNNING')


if __name__ == '__main__':
    import unittest
    unittest.main()
