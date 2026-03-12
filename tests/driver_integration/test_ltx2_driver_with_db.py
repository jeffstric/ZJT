"""
LTX2 RunningHub 驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
import asyncio
from unittest.mock import patch, MagicMock

sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest, mock_get_dynamic_config_value
from task.visual_drivers.ltx2_runninghub_v1_driver import Ltx2RunninghubV1Driver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING, AI_TOOL_STATUS_COMPLETED, AI_TOOL_STATUS_FAILED

LTX2_IMAGE_TO_VIDEO_TYPE = 10


class TestLtx2RunninghubWithDB(BaseVideoDriverTest):
    """LTX2 驱动数据库集成测试"""

    def setUp(self):
        """测试前准备"""
        super().setUp()
        # 使用统一的 mock 配置函数，从 config_unit.yml 获取配置
        with patch('task.visual_drivers.ltx2_runninghub_v1_driver.get_dynamic_config_value', side_effect=mock_get_dynamic_config_value):
            self.driver = Ltx2RunninghubV1Driver()
    
        
    def test_driver_initialization(self):
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'ltx2_runninghub_v1')
        self.assertEqual(self.driver.driver_type, LTX2_IMAGE_TO_VIDEO_TYPE)
    
    def test_build_create_request(self):
        """测试构建创建任务请求参数"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=LTX2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试提示词',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PENDING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        req = asyncio.run(self.driver.build_create_request(tool))
        
        # 验证 url
        self.assertIn('/openapi/v2/run/ai-app/', req['url'])
        self.assertIn('2011014079896358914', req['url'])  # webapp_id
        
        # 验证 method
        self.assertEqual(req['method'], 'POST')
        
        # 验证 json 结构
        self.assertIn('nodeInfoList', req['json'])
        self.assertIsInstance(req['json']['nodeInfoList'], list)
        self.assertEqual(req['json']['instanceType'], 'plus')
        self.assertEqual(req['json']['usePersonalQueue'], 'false')
        
        # 验证 nodeInfoList 包含必要字段
        node_info_list = req['json']['nodeInfoList']
        self.assertGreater(len(node_info_list), 0)
        
        # 查找关键节点
        image_node = next((n for n in node_info_list if n['fieldName'] == 'image'), None)
        self.assertIsNotNone(image_node)
        self.assertEqual(image_node['fieldValue'], 'https://example.com/test.jpg')
        
        prompt_node = next((n for n in node_info_list if n['fieldName'] == 'text' and n['nodeId'] == '96'), None)
        self.assertIsNotNone(prompt_node)
        self.assertEqual(prompt_node['fieldValue'], '测试提示词')
        
        duration_node = next((n for n in node_info_list if n['fieldName'] == 'value' and n['nodeId'] == '52'), None)
        self.assertIsNotNone(duration_node)
        self.assertEqual(duration_node['fieldValue'], '5')
        
        # 验证 headers
        self.assertIn('Authorization', req['headers'])
        self.assertTrue(req['headers']['Authorization'].startswith('Bearer '))
        self.assertEqual(req['headers']['Content-Type'], 'application/json')
    
    def test_build_check_query(self):
        """测试构建查询状态请求参数"""
        project_id = 'ltx2_test_task_123'
        req = self.driver.build_check_query(project_id)
        
        # 验证 url
        self.assertIn('/task/openapi/status', req['url'])
        
        # 验证 method
        self.assertEqual(req['method'], 'POST')
        
        # 验证 json
        self.assertIn('apiKey', req['json'])
        self.assertEqual(req['json']['taskId'], project_id)
        
        # 验证 headers
        self.assertEqual(req['headers']['Content-Type'], 'application/json')
        self.assertEqual(req['headers']['Accept'], 'application/json')
    
    def test_submit_task_success(self):
        """测试提交任务成功 - mock _request"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=LTX2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 LTX2 提交成功',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PROCESSING
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "taskId": "ltx2_task_123",
                "status": "RUNNING",
                "errorCode": "",
                "errorMessage": ""
            }
            
            result = asyncio.run(self.driver.submit_task(tool))
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证 url
            self.assertIn('/openapi/v2/run/ai-app/', call_args.kwargs['url'])
            
            # 验证 method
            self.assertEqual(call_args.kwargs['method'], 'POST')
            
            # 验证 json 中的 nodeInfoList
            node_info_list = call_args.kwargs['json']['nodeInfoList']
            self.assertIsInstance(node_info_list, list)
            
            # 验证关键节点值
            image_node = next((n for n in node_info_list if n['fieldName'] == 'image'), None)
            self.assertEqual(image_node['fieldValue'], 'https://example.com/test.jpg')
            
            prompt_node = next((n for n in node_info_list if n['fieldName'] == 'text' and n['nodeId'] == '96'), None)
            self.assertEqual(prompt_node['fieldValue'], '测试 LTX2 提交成功')
            
            duration_node = next((n for n in node_info_list if n['fieldName'] == 'value' and n['nodeId'] == '52'), None)
            self.assertEqual(duration_node['fieldValue'], '5')
            
            # 验证 headers
            self.assertIn('Authorization', call_args.kwargs['headers'])
            
            # 验证返回结果
            self.assertTrue(result['success'])
            self.assertEqual(result['project_id'], 'ltx2_task_123')
        
        # 模拟业务层更新数据库
        self.update_ai_tool_status(
            task_id,
            status=AI_TOOL_STATUS_PROCESSING,
            project_id=result['project_id']
        )
        
        # 验证数据库已更新 project_id
        tool = self.get_ai_tool_from_db(task_id)
        self.assertEqual(tool.project_id, 'ltx2_task_123')
    
    def test_submit_task_invalid_response(self):
        """测试提交任务响应格式错误 - mock _request"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=LTX2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试响应格式错误',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_FAILED
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        with patch.object(self.driver, '_request') as mock_req:
            # 返回缺少必要字段的响应
            mock_req.return_value = {"errorCode": "INVALID"}
            result = asyncio.run(self.driver.submit_task(tool))
            
            self.assertFalse(result['success'])
    
    def test_submit_task_network_error(self):
        """测试提交任务网络错误 - mock _request"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=LTX2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试网络错误',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_FAILED
        )
        
        tool = self.get_ai_tool_from_db(task_id)
        
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.side_effect = ConnectionError('Network timeout')
            result = asyncio.run(self.driver.submit_task(tool))
            
            self.assertFalse(result['success'])
            self.assertTrue(result['retry'])
    
    def test_check_status_success(self):
        """测试检查状态 - 成功，并更新数据库 - mock _request"""
        # 创建处理中的任务
        task_id = self.create_test_ai_tool(
            ai_tool_type=LTX2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查成功',
            image_path='https://example.com/test.jpg',
            duration=5,
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='ltx2_task_456'
        )
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            # 第一次调用返回 SUCCESS 状态
            # 第二次调用返回 outputs
            mock_req.side_effect = [
                {"code": 0, "msg": "success", "data": "SUCCESS"},
                {"code": 0, "msg": "success", "data": [{"fileUrl": "https://example.com/result.mp4"}]}
            ]
            
            result = self.driver.check_status('ltx2_task_456')
            
            # 验证 _request 被调用两次（status + outputs）
            self.assertEqual(mock_req.call_count, 2)
            
            # 验证第一次调用（查询状态）
            first_call = mock_req.call_args_list[0]
            self.assertIn('/task/openapi/status', first_call.kwargs['url'])
            self.assertEqual(first_call.kwargs['method'], 'POST')
            self.assertEqual(first_call.kwargs['json']['taskId'], 'ltx2_task_456')
            
            # 验证第二次调用（获取输出）
            second_call = mock_req.call_args_list[1]
            self.assertIn('/task/openapi/outputs', second_call.kwargs['url'])
            self.assertEqual(second_call.kwargs['method'], 'POST')
            self.assertEqual(second_call.kwargs['json']['taskId'], 'ltx2_task_456')
            
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
            ai_tool_type=LTX2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查失败',
            image_path='https://example.com/test.jpg',
            duration=5,
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='ltx2_task_789'
        )
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            # 返回 FAILED 状态
            mock_req.return_value = {"code": 0, "msg": "success", "data": "FAILED"}
            
            result = self.driver.check_status('ltx2_task_789')
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证调用参数
            self.assertIn('/task/openapi/status', call_args.kwargs['url'])
            self.assertEqual(call_args.kwargs['method'], 'POST')
            self.assertEqual(call_args.kwargs['json']['taskId'], 'ltx2_task_789')
            
            # 验证返回结果
            self.assertEqual(result['status'], 'FAILED')
        
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
            ai_tool_type=LTX2_IMAGE_TO_VIDEO_TYPE,
            prompt='测试状态检查处理中',
            image_path='https://example.com/test.jpg',
            duration=5,
            ratio='9:16',
            status=AI_TOOL_STATUS_PROCESSING,
            project_id='ltx2_task_999'
        )
        
        # Mock _request 返回原始 API 响应
        with patch.object(self.driver, '_request') as mock_req:
            # 返回 RUNNING 状态
            mock_req.return_value = {"code": 0, "msg": "success", "data": "RUNNING"}
            
            result = self.driver.check_status('ltx2_task_999')
            
            # 验证 _request 被调用一次
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            
            # 验证调用参数
            self.assertIn('/task/openapi/status', call_args.kwargs['url'])
            self.assertEqual(call_args.kwargs['method'], 'POST')
            self.assertEqual(call_args.kwargs['json']['taskId'], 'ltx2_task_999')
            
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
