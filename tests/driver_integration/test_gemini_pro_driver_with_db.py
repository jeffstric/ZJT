"""
Gemini Pro Duomi 驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['duomi_api_requset'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.video_drivers.gemini_pro_duomi_v1_driver import GeminiProDuomiV1Driver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING

GEMINI_PRO_IMAGE_TO_VIDEO_TYPE = 7


class TestGeminiProDuomiWithDB(BaseVideoDriverTest):
    """Gemini Pro 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = GeminiProDuomiV1Driver()
    
    def tearDown(self):
        """测试结束后：不做任何操作，让基类处理事务回滚"""
        pass
    
    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'gemini_pro_duomi_v1')
        self.assertEqual(self.driver.driver_type, GEMINI_PRO_IMAGE_TO_VIDEO_TYPE)
    
    @patch('task.video_drivers.gemini_pro_duomi_v1_driver.create_ai_image')
    def test_submit_task_success(self, mock_api):
        """测试提交任务 - 成功"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_PRO_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 Gemini Pro 提交成功',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        mock_api.return_value = {
            "code": 200,
            "msg": "success",
            "data": {"task_id": "gemini_pro_task_123"}
        }
        
        result = self.driver.submit_task(tool)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'gemini_pro_task_123')
    
    @patch('task.video_drivers.gemini_pro_duomi_v1_driver.create_ai_image')
    def test_submit_task_user_error(self, mock_api):
        """测试提交任务 - 用户错误"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_PRO_IMAGE_TO_VIDEO_TYPE,
            prompt='测试用户错误',
            image_path='invalid_url',
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        mock_api.return_value = {
            "code": 400,
            "msg": "图片URL格式错误"
        }
        
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertFalse(result['retry'])
    
    @patch('task.video_drivers.gemini_pro_duomi_v1_driver.create_ai_image')
    def test_submit_task_network_error(self, mock_api):
        """测试提交任务 - 网络错误"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_PRO_IMAGE_TO_VIDEO_TYPE,
            prompt='测试网络错误',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        mock_api.side_effect = ConnectionError('Network timeout')
        
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])
    
    @patch('task.video_drivers.gemini_pro_duomi_v1_driver.get_ai_task_result')
    def test_check_status_success(self, mock_api):
        """测试检查状态 - 成功"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_PRO_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查成功',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='gemini_pro_task_456'
        )
        
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "status": 1,
                "mediaUrl": "https://example.com/result.png"
            }
        }
        
        result = self.driver.check_status('gemini_pro_task_456')
        
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result.png')
    
    @patch('task.video_drivers.gemini_pro_duomi_v1_driver.get_ai_task_result')
    def test_check_status_failed(self, mock_api):
        """测试检查状态 - 失败"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_PRO_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查失败',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='gemini_pro_task_789'
        )
        
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "status": 2,
                "reason": "内容违规"
            }
        }
        
        result = self.driver.check_status('gemini_pro_task_789')
        
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('error', result)
    
    @patch('task.video_drivers.gemini_pro_duomi_v1_driver.get_ai_task_result')
    def test_check_status_processing(self, mock_api):
        """测试检查状态 - 处理中"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_PRO_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查处理中',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='gemini_pro_task_999'
        )
        
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "status": 0
            }
        }
        
        result = self.driver.check_status('gemini_pro_task_999')
        
        self.assertEqual(result['status'], 'RUNNING')


if __name__ == '__main__':
    import unittest
    unittest.main()
