"""
Vidu 驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest, mock_get_dynamic_config_value
from task.visual_drivers.vidu_default_driver import ViduDefaultDriver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING, AI_TOOL_STATUS_COMPLETED, AI_TOOL_STATUS_FAILED

VIDU_IMAGE_TO_VIDEO_TYPE = 14


class TestViduDefaultWithDB(BaseVideoDriverTest):
    """Vidu 驱动数据库集成测试"""

    def setUp(self):
        """测试前准备"""
        super().setUp()
        # 使用统一的 mock 配置函数，从 config_unit.yml 获取配置
        with patch('task.visual_drivers.vidu_default_driver.get_dynamic_config_value', side_effect=mock_get_dynamic_config_value):
            self.driver = ViduDefaultDriver()

    def test_driver_initialization(self):
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'vidu_default')
        self.assertEqual(self.driver.driver_type, VIDU_IMAGE_TO_VIDEO_TYPE)
    
    def test_build_create_request_single_image(self):
        """测试构建创建任务请求参数 - 单图模式"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试提示词',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        req = self.driver.build_create_request(tool)
        
        # 验证 url（单图模式）
        self.assertIn('/ent/v2/img2video', req['url'])
        
        # 验证 method
        self.assertEqual(req['method'], 'POST')
        
        # 验证 json 结构
        self.assertEqual(req['json']['model'], 'viduq2-pro-fast')
        self.assertEqual(req['json']['images'], ['https://example.com/test.jpg'])
        self.assertEqual(req['json']['prompt'], '测试提示词')
        self.assertEqual(req['json']['duration'], 5)
        self.assertEqual(req['json']['resolution'], '720p')
        self.assertEqual(req['json']['movement_amplitude'], 'auto')
        
        # 验证 headers
        self.assertIn('Authorization', req['headers'])
        self.assertTrue(req['headers']['Authorization'].startswith('Token '))
        self.assertEqual(req['headers']['Content-Type'], 'application/json')
    
    def test_build_create_request_dual_image(self):
        """测试构建创建任务请求参数 - 双图模式"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试双图提示词',
            image_path='https://example.com/start.jpg,https://example.com/end.jpg',
            duration=8,
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        req = self.driver.build_create_request(tool)
        
        # 验证 url（双图模式）
        self.assertIn('/ent/v2/start-end2video', req['url'])
        
        # 验证 method
        self.assertEqual(req['method'], 'POST')
        
        # 验证 json 结构
        self.assertEqual(req['json']['model'], 'viduq2-pro-fast')
        self.assertEqual(req['json']['images'], ['https://example.com/start.jpg', 'https://example.com/end.jpg'])
        self.assertEqual(req['json']['prompt'], '测试双图提示词')
        self.assertEqual(req['json']['duration'], '8')
        self.assertEqual(req['json']['resolution'], '720p')
        self.assertEqual(req['json']['movement_amplitude'], 'auto')
        
        # 验证 headers
        self.assertIn('Authorization', req['headers'])
    
    def test_build_check_query(self):
        """测试构建查询状态请求参数"""
        project_id = 'vidu_test_task_123'
        req = self.driver.build_check_query(project_id)
        
        # 验证 url
        self.assertIn(f'/ent/v2/tasks/{project_id}/creations', req['url'])
        
        # 验证 method
        self.assertEqual(req['method'], 'GET')
        
        # 验证 json 为 None（GET请求）
        self.assertIsNone(req['json'])
        
        # 验证 headers
        self.assertIn('Authorization', req['headers'])
        self.assertTrue(req['headers']['Authorization'].startswith('Token '))
    
    def test_submit_task_success_single_image(self):
        """测试提交任务 - 成功（单图模式）- mock _request"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 Vidu 单图提交成功',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PROCESSING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "task_id": "vidu_task_123",
                "state": "created",
                "model": "Vidu3.1-图生视频-720p",
                "credits": 4
            }
            
            result = self.driver.submit_task(tool)
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证 url（单图模式）
            self.assertIn('/ent/v2/img2video', call_args.kwargs['url'])
            
            # 验证 method
            self.assertEqual(call_args.kwargs['method'], 'POST')
            
            # 验证 json 参数
            self.assertEqual(call_args.kwargs['json']['images'], ['https://example.com/test.jpg'])
            self.assertEqual(call_args.kwargs['json']['prompt'], '测试 Vidu 单图提交成功')
            self.assertEqual(call_args.kwargs['json']['duration'], 5)
            self.assertEqual(call_args.kwargs['json']['resolution'], '720p')
            self.assertEqual(call_args.kwargs['json']['movement_amplitude'], 'auto')
            
            # 验证 headers
            self.assertIn('Authorization', call_args.kwargs['headers'])
            
            # 验证返回结果
            self.assertTrue(result['success'])
            self.assertEqual(result['project_id'], 'vidu_task_123')
        
        # 模拟业务层更新数据库
        self.update_ai_tool_status(
            task_id,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id=result['project_id']
        )
        
        # 验证数据库已更新 project_id
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.project_id, 'vidu_task_123')
    
    def test_submit_task_success_dual_image(self):
        """测试提交任务 - 成功（双图模式）- mock _request"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 Vidu 双图提交成功',
            image_path='https://example.com/start.jpg,https://example.com/end.jpg',
            duration=8,
            status=AI_TOOL_STATUS_PROCESSING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "task_id": "vidu_task_dual_123",
                "state": "created",
                "model": "Vidu3.1-首尾图生视频-720p",
                "credits": 8
            }
            
            result = self.driver.submit_task(tool)
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证 url（双图模式）
            self.assertIn('/ent/v2/start-end2video', call_args.kwargs['url'])
            
            # 验证 method
            self.assertEqual(call_args.kwargs['method'], 'POST')
            
            # 验证 json 参数
            self.assertEqual(call_args.kwargs['json']['images'], ['https://example.com/start.jpg', 'https://example.com/end.jpg'])
            self.assertEqual(call_args.kwargs['json']['prompt'], '测试 Vidu 双图提交成功')
            self.assertEqual(call_args.kwargs['json']['duration'], '8')
            self.assertEqual(call_args.kwargs['json']['resolution'], '720p')
            self.assertEqual(call_args.kwargs['json']['movement_amplitude'], 'auto')
            
            # 验证 headers
            self.assertIn('Authorization', call_args.kwargs['headers'])
            
            # 验证返回结果
            self.assertTrue(result['success'])
            self.assertEqual(result['project_id'], 'vidu_task_dual_123')
        
        # 模拟业务层更新数据库
        self.update_ai_tool_status(
            task_id,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id=result['project_id']
        )
        
        # 验证数据库已更新 project_id
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.project_id, 'vidu_task_dual_123')
    
    def test_submit_task_invalid_response(self):
        """测试提交任务响应格式错误 - mock _request"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试响应格式错误',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_FAILED
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        # Mock _request 返回业务错误
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {"error": "invalid request"}
            
            result = self.driver.submit_task(tool)
            
            self.assertFalse(result['success'])
            self.assertEqual(result['error_type'], 'USER')
    
    def test_submit_task_network_error(self):
        """测试提交任务网络错误 - mock _request"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试网络错误',
            image_path='https://example.com/test.jpg',
            duration=5,
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
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查成功',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='vidu_task_456'
        )
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "id": "vidu_task_456",
                "state": "success",
                "creations": [{"url": "https://example.com/result.mp4"}],
                "credits": 4
            }
            
            result = self.driver.check_status('vidu_task_456')
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证调用参数
            self.assertIn('/ent/v2/tasks/vidu_task_456/creations', call_args.kwargs['url'])
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
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查失败',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='vidu_task_789'
        )
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "id": "vidu_task_789",
                "state": "failed",
                "creations": [],
                "err_code": "CONTENT_VIOLATION"
            }
            
            result = self.driver.check_status('vidu_task_789')
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证调用参数
            self.assertIn('/ent/v2/tasks/vidu_task_789/creations', call_args.kwargs['url'])
            self.assertEqual(call_args.kwargs['method'], 'GET')
            
            # 验证返回结果
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['error'], 'CONTENT_VIOLATION')
        
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
            ai_tool_type=VIDU_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查处理中',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='vidu_task_999'
        )
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "id": "vidu_task_999",
                "state": "processing",
                "creations": []
            }
            
            result = self.driver.check_status('vidu_task_999')
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证调用参数
            self.assertIn('/ent/v2/tasks/vidu_task_999/creations', call_args.kwargs['url'])
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
