"""
VEO3 Duomi 驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['duomi_api_requset'] = MagicMock()
sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest
from task.visual_drivers.veo3_duomi_v1_driver import Veo3DuomiV1Driver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING, AI_TOOL_STATUS_COMPLETED, AI_TOOL_STATUS_FAILED

VEO3_IMAGE_TO_VIDEO_TYPE = 15


class TestVeo3DuomiWithDB(BaseVideoDriverTest):
    """VEO3 驱动数据库集成测试"""
    
    def setUp(self):
        super().setUp()
        self.driver = Veo3DuomiV1Driver()

    
    def test_driver_initialization(self):
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'veo3_duomi_v1')
        self.assertEqual(self.driver.driver_type, VEO3_IMAGE_TO_VIDEO_TYPE)
    
    @patch('task.visual_drivers.veo3_duomi_v1_driver.create_image_to_video_veo')
    def test_submit_task_success(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 VEO3 提交成功',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        mock_api.return_value = {"id": "veo3_task_123"}
        result = self.driver.submit_task(tool)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'veo3_task_123')
        
        # 模拟业务层更新数据库：将 project_id 写入数据库
        self.update_ai_tool_status(
            task_id,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id=result['project_id']
        )
        
        # 验证数据库已更新 project_id
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.project_id, 'veo3_task_123')
    
    @patch('task.visual_drivers.veo3_duomi_v1_driver.create_image_to_video_veo')
    def test_submit_task_invalid_response(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试响应格式错误',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_FAILED
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        mock_api.return_value = {"error": "invalid"}
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'SYSTEM')
    
    @patch('task.visual_drivers.veo3_duomi_v1_driver.create_image_to_video_veo')
    def test_submit_task_network_error(self, mock_api):
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试网络错误',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_FAILED
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        mock_api.side_effect = ConnectionError('Network timeout')
        result = self.driver.submit_task(tool)
        
        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])
    
    @patch('task.visual_drivers.veo3_duomi_v1_driver.get_ai_task_result')
    def test_check_status_success(self, mock_api):
        """测试检查状态 - 成功，并更新数据库"""
        # 创建处理中的任务
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查成功',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='veo3_task_456'
        )
        
        # Mock API返回成功状态
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {"status": 1, "mediaUrl": "https://example.com/result.mp4"}
        }
        
        result = self.driver.check_status('veo3_task_456')
        
        # 验证调用参数
        mock_api.assert_called_once_with(project_id='veo3_task_456', is_video=True)
        
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
    
    @patch('task.visual_drivers.veo3_duomi_v1_driver.get_ai_task_result')
    def test_check_status_failed(self, mock_api):
        """测试检查状态 - 失败，并更新数据库"""
        # 创建处理中的任务
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查失败',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='veo3_task_789'
        )
        
        # Mock API返回成功状态
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {"status": 2, "reason": "内容违规"}
        }
        
        result = self.driver.check_status('veo3_task_789')
        
        # 验证调用参数
        mock_api.assert_called_once_with(project_id='veo3_task_789', is_video=True)
        
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
    
    @patch('task.visual_drivers.veo3_duomi_v1_driver.get_ai_task_result')
    def test_check_status_processing(self, mock_api):
        """测试检查状态 - 处理中，数据库状态保持不变"""
        # 创建处理中的任务
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查处理中',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='veo3_task_999'
        )
        
        # Mock API返回成功状态
        mock_api.return_value = {
            "code": 0,
            "msg": "success",
            "data": {"status": 0}
        }
        
        result = self.driver.check_status('veo3_task_999')
        
        # 验证调用参数
        mock_api.assert_called_once_with(project_id='veo3_task_999', is_video=True)
        
        self.assertEqual(result['status'], 'RUNNING')
        
        # 处理中状态，数据库不更新（保持 PROCESSING 状态）
        # 验证数据库状态未改变
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.status, AI_TOOL_STATUS_PROCESSING)
        self.assertIsNone(tool.result_url)  # 仍然没有结果


if __name__ == '__main__':
    import unittest
    unittest.main()
