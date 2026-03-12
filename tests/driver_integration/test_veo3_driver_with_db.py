"""
VEO3 Duomi 驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest, mock_get_dynamic_config_value
from task.visual_drivers.veo3_duomi_v1_driver import Veo3DuomiV1Driver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING, AI_TOOL_STATUS_COMPLETED, AI_TOOL_STATUS_FAILED

VEO3_IMAGE_TO_VIDEO_TYPE = 15


class TestVeo3DuomiWithDB(BaseVideoDriverTest):
    """VEO3 驱动数据库集成测试"""

    def setUp(self):
        """测试前准备"""
        super().setUp()
        # 使用统一的 mock 配置函数，从 config_unit.yml 获取配置
        with patch('task.visual_drivers.veo3_duomi_v1_driver.get_dynamic_config_value', side_effect=mock_get_dynamic_config_value):
            self.driver = Veo3DuomiV1Driver()

    
    def test_driver_initialization(self):
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'veo3_duomi_v1')
        self.assertEqual(self.driver.driver_type, VEO3_IMAGE_TO_VIDEO_TYPE)
    
    def test_build_create_request(self):
        """测试构建创建任务请求参数"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试提示词',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        req = self.driver.build_create_request(tool)
        
        # 验证 url
        self.assertIn('/v1/videos/generations', req['url'])
        
        # 验证 method
        self.assertEqual(req['method'], 'POST')
        
        # 验证 json 结构
        self.assertEqual(req['json']['model'], 'veo3.1-fast')
        self.assertEqual(req['json']['prompt'], '测试提示词')
        self.assertEqual(req['json']['aspect_ratio'], '9:16')
        self.assertEqual(req['json']['duration'], 8)  # VEO3 固定8秒
        self.assertEqual(req['json']['image_urls'], ['https://example.com/test.jpg'])
        self.assertEqual(req['json']['generation_type'], 'FIRST&LAST')
        
        # 验证 headers
        self.assertIn('Authorization', req['headers'])
        self.assertEqual(req['headers']['Content-Type'], 'application/json')
    
    def test_build_check_query(self):
        """测试构建查询状态请求参数"""
        project_id = 'veo3_test_task_123'
        req = self.driver.build_check_query(project_id)
        
        # 验证 url
        self.assertIn(f'/v1/videos/tasks/{project_id}', req['url'])
        
        # 验证 method
        self.assertEqual(req['method'], 'GET')
        
        # 验证 json 为 None（GET请求）
        self.assertIsNone(req['json'])
        
        # 验证 headers
        self.assertIn('Authorization', req['headers'])
    
    def test_submit_task_success(self):
        """测试提交任务成功 - mock _request"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 VEO3 提交成功',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "id": "veo3_task_123",
                "state": "processing",
                "message": "Task created successfully"
            }
            
            result = self.driver.submit_task(tool)
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证 url
            self.assertIn('/v1/videos/generations', call_args.kwargs['url'])
            
            # 验证 method
            self.assertEqual(call_args.kwargs['method'], 'POST')
            
            # 验证 json 参数
            self.assertEqual(call_args.kwargs['json']['model'], 'veo3.1-fast')
            self.assertEqual(call_args.kwargs['json']['prompt'], '测试 VEO3 提交成功')
            self.assertEqual(call_args.kwargs['json']['aspect_ratio'], '9:16')
            self.assertEqual(call_args.kwargs['json']['duration'], 8)
            self.assertEqual(call_args.kwargs['json']['image_urls'], ['https://example.com/test.jpg'])
            
            # 验证 headers
            self.assertIn('Authorization', call_args.kwargs['headers'])
            
            # 验证返回结果
            self.assertTrue(result['success'])
            self.assertEqual(result['project_id'], 'veo3_task_123')
        
        # 模拟业务层更新数据库
        self.update_ai_tool_status(
            task_id,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id=result['project_id']
        )
        
        # 验证数据库已更新 project_id
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.project_id, 'veo3_task_123')
    
    def test_submit_task_invalid_response(self):
        """测试提交任务响应格式错误 - mock _request"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试响应格式错误',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_FAILED
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        with patch.object(self.driver, '_request') as mock_req:
            # 返回缺少必要字段的响应
            mock_req.return_value = {"error": "invalid"}
            result = self.driver.submit_task(tool)
            
            self.assertFalse(result['success'])
            self.assertEqual(result['error_type'], 'SYSTEM')
    
    def test_submit_task_network_error(self):
        """测试提交任务网络错误 - mock _request"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试网络错误',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_FAILED
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.side_effect = ConnectionError('Network timeout')
            result = self.driver.submit_task(tool)
            
            self.assertFalse(result['success'])
            self.assertTrue(result['retry'])
    
    def test_check_status_success(self):
        """测试检查状态 - 成功，并更新数据库 - mock _request"""
        # 创建处理中的任务
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查成功',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='veo3_task_456'
        )
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "id": "veo3_task_456",
                "state": "succeeded",
                "data": {
                    "videos": [{"url": "https://example.com/result.mp4"}]
                }
            }
            
            result = self.driver.check_status('veo3_task_456')
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证调用参数
            self.assertIn('/v1/videos/tasks/veo3_task_456', call_args.kwargs['url'])
            self.assertEqual(call_args.kwargs['method'], 'GET')
            
            # 验证返回结果
            self.assertEqual(result['status'], 'SUCCESS')
            self.assertEqual(result['result_url'], 'https://example.com/result.mp4')
        
        # 模拟业务层更新数据库
        self.update_ai_tool_status(
            task_id,
            status=AI_TOOL_STATUS_COMPLETED,
            result_url=result.get('result_url', '')
        )
        
        # 验证数据库状态已更新
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.status, AI_TOOL_STATUS_COMPLETED)
    
    def test_check_status_failed(self):
        """测试检查状态 - 失败，并更新数据库 - mock _request"""
        # 创建处理中的任务
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查失败',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='veo3_task_789'
        )
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "id": "veo3_task_789",
                "state": "error",
                "message": "内容违规"
            }
            
            result = self.driver.check_status('veo3_task_789')
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证调用参数
            self.assertIn('/v1/videos/tasks/veo3_task_789', call_args.kwargs['url'])
            self.assertEqual(call_args.kwargs['method'], 'GET')
            
            # 验证返回结果
            self.assertEqual(result['status'], 'FAILED')
            # 注意：驱动在 state="error" 时会设置 code=1，返回带前缀的错误消息
            self.assertEqual(result['error'], '查询任务状态失败: 内容违规')
        
        # 模拟业务层更新数据库
        self.update_ai_tool_status(
            task_id,
            status=AI_TOOL_STATUS_FAILED,
            message=result.get('error', '任务失败')
        )
        
        # 验证数据库状态已更新
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.status, AI_TOOL_STATUS_FAILED)
    
    def test_check_status_processing(self):
        """测试检查状态 - 处理中，数据库状态保持不变 - mock _request"""
        # 创建处理中的任务
        task_id = self.create_test_ai_tool(
            ai_tool_type=VEO3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查处理中',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='veo3_task_999'
        )
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "id": "veo3_task_999",
                "state": "processing",
                "message": "Task is being processed"
            }
            
            result = self.driver.check_status('veo3_task_999')
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证调用参数
            self.assertIn('/v1/videos/tasks/veo3_task_999', call_args.kwargs['url'])
            self.assertEqual(call_args.kwargs['method'], 'GET')
            
            # 验证返回结果
            self.assertEqual(result['status'], 'RUNNING')
        
        # 处理中状态，数据库不更新（保持 PROCESSING 状态）
        # 验证数据库状态未改变
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.status, AI_TOOL_STATUS_PROCESSING)
        self.assertIsNone(tool.result_url)


if __name__ == '__main__':
    import unittest
    unittest.main()
