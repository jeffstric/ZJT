"""
Gemini Duomi 驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['duomi_api_requset'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.visual_drivers.gemini_duomi_v1_driver import GeminiDuomiV1Driver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING, AI_TOOL_STATUS_COMPLETED, AI_TOOL_STATUS_FAILED

GEMINI_IMAGE_TO_VIDEO_TYPE = 1


class TestGeminiDuomiWithDB(BaseVideoDriverTest):
    """Gemini 驱动数据库集成测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.driver = GeminiDuomiV1Driver()
    
    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'gemini_duomi_v1')
        self.assertEqual(self.driver.driver_type, GEMINI_IMAGE_TO_VIDEO_TYPE)
    
    @patch('task.visual_drivers.gemini_duomi_v1_driver.create_ai_image')
    def test_submit_task_success(self, mock_api):
        """测试提交任务 - 成功"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 Gemini 提交成功',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.status, AI_TOOL_STATUS_PROCESSING)
        
        # Gemini API返回格式：{"code": 200, "msg": "success", "data": {"task_id": "xxx"}}
        mock_api.return_value = {
            "code": 200,
            "msg": "success",
            "data": {"task_id": "gemini_task_123"}
        }
        
        result = self.driver.submit_task(tool)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'gemini_task_123')
        
        # 模拟业务层更新数据库：将 project_id 写入数据库
        self.update_ai_tool_status(
            task_id,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id=result['project_id']
        )
        
        # 验证数据库已更新 project_id
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.project_id, 'gemini_task_123')
    
    @patch('task.visual_drivers.gemini_duomi_v1_driver.create_ai_image')
    def test_submit_task_user_error(self, mock_api):
        """测试提交任务 - 用户错误"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_IMAGE_TO_VIDEO_TYPE,
            prompt='测试用户错误',
            image_path='invalid_url',
            ratio='9:16',
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        # API返回业务错误（code != 200）
        mock_api.return_value = {
            "code": 400,
            "msg": "图片URL格式错误"
        }
        
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertFalse(result['retry'])
    
    @patch('task.visual_drivers.gemini_duomi_v1_driver.create_ai_image')
    def test_submit_task_network_error(self, mock_api):
        """测试提交任务 - 网络错误"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_IMAGE_TO_VIDEO_TYPE,
            prompt='测试网络错误',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_FAILED
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        # Mock 网络超时异常
        mock_api.side_effect = ConnectionError('Network timeout')
        
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])
    
    @patch('task.visual_drivers.gemini_duomi_v1_driver.get_ai_task_result')
    def test_check_status_success(self, mock_api):
        """测试检查状态 - 成功"""
        # API返回成功状态（status=1表示成功）
        """测试检查状态 - 成功，并更新数据库"""
        # 创建处理中的任务
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查成功',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='gemini_task_456'
        )
        
        # Mock API返回成功状态
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "status": 1,
                "mediaUrl": "https://example.com/result.png"
            }
        }
        
        result = self.driver.check_status('gemini_task_456')
        
        # 验证调用参数
        mock_api.assert_called_once_with(project_id='gemini_task_456', is_video=False)
        
        
        self.assertEqual(result['status'], 'SUCCESS')
        
        # 模拟业务层更新数据库
        from config.constant import AI_TOOL_STATUS_COMPLETED
        self.update_ai_tool_status(
            task_id,
            status=AI_TOOL_STATUS_COMPLETED,
            result_url=result.get('result_url', '')
        )
        
        # 验证数据库状态已更新
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.status, AI_TOOL_STATUS_COMPLETED)
    
    @patch('task.visual_drivers.gemini_duomi_v1_driver.get_ai_task_result')
    def test_check_status_failed(self, mock_api):
        """测试检查状态 - 失败"""
        # API返回失败状态（status=2表示失败）
        """测试检查状态 - 失败，并更新数据库"""
        # 创建处理中的任务
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查失败',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='gemini_task_789'
        )
        
        # Mock API返回成功状态
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "status": 2,
                "reason": "内容违规"
            }
        }
        
        result = self.driver.check_status('gemini_task_789')
        
        # 验证调用参数
        mock_api.assert_called_once_with(project_id='gemini_task_789', is_video=False)
        
        
        self.assertEqual(result['status'], 'FAILED')
        
        # 模拟业务层更新数据库
        from config.constant import AI_TOOL_STATUS_FAILED
        self.update_ai_tool_status(
            task_id,
            status=AI_TOOL_STATUS_FAILED,
            message=result.get('error', '任务失败')
        )
        
        # 验证数据库状态已更新
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.status, AI_TOOL_STATUS_FAILED)
    
    @patch('task.visual_drivers.gemini_duomi_v1_driver.get_ai_task_result')
    def test_check_status_processing(self, mock_api):
        """测试检查状态 - 处理中"""
        # API返回处理中状态（status=0表示处理中）
        """测试检查状态 - 处理中，数据库状态保持不变"""
        # 创建处理中的任务
        task_id = self.create_test_ai_tool(
            ai_tool_type=GEMINI_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查处理中',
            image_path='https://example.com/test.jpg',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='gemini_task_999'
        )
        
        # Mock API返回成功状态
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "status": 0
            }
        }
        
        result = self.driver.check_status('gemini_task_999')
        
        # 验证调用参数
        mock_api.assert_called_once_with(project_id='gemini_task_999', is_video=False)
        
        
        self.assertEqual(result['status'], 'RUNNING')
        
        # 处理中状态，数据库不更新（保持 PROCESSING 状态）
        # 验证数据库状态未改变
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.status, AI_TOOL_STATUS_PROCESSING)
        self.assertIsNone(tool.result_url)  # 仍然没有结果


if __name__ == '__main__':
    import unittest
    unittest.main()
