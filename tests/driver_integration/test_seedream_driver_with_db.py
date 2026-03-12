"""
Seedream 5.0 火山引擎驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['utils.sentry_util'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest, mock_get_dynamic_config_value
from task.visual_drivers.seedream_volcengine_v1_driver import Seedream5VolcengineV1Driver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING, AI_TOOL_STATUS_COMPLETED, AI_TOOL_STATUS_FAILED, TaskTypeId

SEEDREAM_TEXT_TO_IMAGE_TYPE = TaskTypeId.SEEDREAM_TEXT_TO_IMAGE


class TestSeedreamVolcengineWithDB(BaseVideoDriverTest):
    """Seedream 5.0 火山引擎驱动数据库集成测试"""

    def setUp(self):
        """测试前准备"""
        super().setUp()
        # 使用统一的 mock 配置函数，从 config_unit.yml 获取配置
        with patch('task.visual_drivers.seedream_volcengine_v1_driver.get_dynamic_config_value', side_effect=mock_get_dynamic_config_value):
            self.driver = Seedream5VolcengineV1Driver()

    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'seedream5_volcengine_v1')
        self.assertEqual(self.driver.driver_type, SEEDREAM_TEXT_TO_IMAGE_TYPE)

    def test_build_create_request(self):
        """测试构建创建任务请求参数"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=SEEDREAM_TEXT_TO_IMAGE_TYPE,
            prompt='一个女孩',
            ratio='9:16',
            image_size='2K',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)
        req = self.driver.build_create_request(tool)

        # 验证 url
        self.assertIn('/api/v3/images/generations', req['url'])
        self.assertIn('ark.cn-beijing.volces.com', req['url'])

        # 验证 method
        self.assertEqual(req['method'], 'POST')

        # 验证 json 结构
        self.assertEqual(req['json']['model'], 'doubao-seedream-5-0-260128')
        self.assertEqual(req['json']['prompt'], '一个女孩')
        # size 是像素尺寸，9:16 + 2K = 1600x2848
        self.assertEqual(req['json']['size'], '1600x2848')
        self.assertEqual(req['json']['output_format'], 'png')
        self.assertEqual(req['json']['watermark'], False)

        # 验证 headers
        self.assertIn('Authorization', req['headers'])
        self.assertEqual(req['headers']['Content-Type'], 'application/json')

    def test_build_create_request_default_size(self):
        """测试默认图片尺寸"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=SEEDREAM_TEXT_TO_IMAGE_TYPE,
            prompt='测试提示词',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)
        req = self.driver.build_create_request(tool)

        # 默认尺寸应该是 2K，默认比例 1:1 -> 2048x2048
        self.assertEqual(req['json']['size'], '2048x2048')

    def test_build_create_request_3k_size(self):
        """测试 3K 图片尺寸"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=SEEDREAM_TEXT_TO_IMAGE_TYPE,
            prompt='测试提示词',
            image_size='3K',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)
        req = self.driver.build_create_request(tool)

        # 3K + 默认比例 1:1 -> 3072x3072
        self.assertEqual(req['json']['size'], '3072x3072')

    def test_build_create_request_4k_size(self):
        """测试 4K 图片尺寸"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=SEEDREAM_TEXT_TO_IMAGE_TYPE,
            prompt='测试提示词',
            image_size='4K',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)
        req = self.driver.build_create_request(tool)

        # 4K + 默认比例 1:1 -> 4096x4096
        self.assertEqual(req['json']['size'], '4096x4096')

    def test_build_check_query_empty(self):
        """测试构建查询状态请求参数（同步API不需要轮询）"""
        project_id = 'test_project_123'
        req = self.driver.build_check_query(project_id)

        # 同步 API 不需要轮询，返回空字典
        self.assertEqual(req, {})

    def test_check_status_always_success(self):
        """测试 check_status 总是返回成功（同步API）"""
        result = self.driver.check_status('any_project_id')

        self.assertEqual(result['status'], 'SUCCESS')

    @patch.object(Seedream5VolcengineV1Driver, '_request')
    def test_submit_task_success(self, mock_request):
        """测试提交任务成功 - 基于实际 API 响应"""
        # 模拟 API 成功响应（基于用户提供的实际日志）
        mock_request.return_value = {
            'model': 'doubao-seedream-5-0-260128',
            'created': 1772622963,
            'data': [{
                'url': 'https://ark-acg-cn-beijing.tos-cn-beijing.volces.com/doubao-seedream-5-0/0217726229450631201fb9e16e3f5837dd939723f9496115a8934_0.png?X-Tos-Algorithm=TOS4-HMAC-SHA256&X-Tos-Credential=REDACTED_CREDENTIAL %2F20260304%2Fcn-beijing%2Ftos%2Frequest&X-Tos-Date=20260304T111603Z&X-Tos-Expires=86400&X-Tos-Signature=0fdfb6594f353cc395b1bdb0251517eea510e50c9efe2baaa70967055e5c3569&X-Tos-SignedHeaders=host',
                'size': '2048x2048'
            }],
            'usage': {
                'generated_images': 1,
                'output_tokens': 16384,
                'total_tokens': 16384
            }
        }

        task_id = self.create_test_ai_tool(
            ai_tool_type=SEEDREAM_TEXT_TO_IMAGE_TYPE,
            prompt='一个女孩',
            ratio='9:16',
            image_size='2K',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)
        result = self.driver.submit_task(tool)

        # 验证结果
        self.assertTrue(result['success'])
        self.assertTrue(result['sync_mode'])
        self.assertIn('ark-acg-cn-beijing.tos-cn-beijing.volces.com', result['result_url'])
        self.assertIn('doubao-seedream-5-0', result['result_url'])

        # 验证 _request 被正确调用
        self.assertEqual(mock_request.call_count, 1)
        call_args = mock_request.call_args

        # 验证请求参数
        self.assertIn('ark.cn-beijing.volces.com', call_args.kwargs['url'])
        self.assertEqual(call_args.kwargs['method'], 'POST')
        self.assertEqual(call_args.kwargs['json']['model'], 'doubao-seedream-5-0-260128')
        self.assertEqual(call_args.kwargs['json']['prompt'], '一个女孩')
        # 9:16 + 2K = 1600x2848
        self.assertEqual(call_args.kwargs['json']['size'], '1600x2848')

    @patch.object(Seedream5VolcengineV1Driver, '_request')
    def test_submit_task_api_error(self, mock_request):
        """测试提交任务 API 错误"""
        mock_request.return_value = {
            'error': {
                'code': 'InvalidAPIKey',
                'message': 'Invalid API key provided'
            }
        }

        task_id = self.create_test_ai_tool(
            ai_tool_type=SEEDREAM_TEXT_TO_IMAGE_TYPE,
            prompt='测试提示词',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)
        result = self.driver.submit_task(tool)

        # 验证结果
        self.assertFalse(result['success'])
        self.assertIn('error', result)

    @patch.object(Seedream5VolcengineV1Driver, '_request')
    def test_submit_task_empty_data(self, mock_request):
        """测试提交任务返回空数据"""
        mock_request.return_value = {
            'model': 'doubao-seedream-5-0-260128',
            'created': 1772622963,
            'data': []
        }

        task_id = self.create_test_ai_tool(
            ai_tool_type=SEEDREAM_TEXT_TO_IMAGE_TYPE,
            prompt='测试提示词',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)
        result = self.driver.submit_task(tool)

        # 验证结果
        self.assertFalse(result['success'])

    @patch.object(Seedream5VolcengineV1Driver, '_request')
    def test_submit_task_network_error(self, mock_request):
        """测试网络错误"""
        mock_request.side_effect = Exception("Connection timeout")

        task_id = self.create_test_ai_tool(
            ai_tool_type=SEEDREAM_TEXT_TO_IMAGE_TYPE,
            prompt='测试提示词',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)
        result = self.driver.submit_task(tool)

        # 验证结果
        self.assertFalse(result['success'])
        self.assertTrue(result.get('retry', False))

    def test_validate_submit_response_success(self):
        """测试验证成功响应"""
        response = {
            'data': [{
                'url': 'https://example.com/image.png',
                'size': '2048x2048'
            }]
        }

        is_valid, error = self.driver._validate_submit_response(response)

        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_submit_response_missing_data(self):
        """测试验证响应缺少 data 字段"""
        response = {'model': 'test'}

        is_valid, error = self.driver._validate_submit_response(response)

        self.assertFalse(is_valid)
        self.assertIn('data', error)

    def test_validate_submit_response_empty_data(self):
        """测试验证响应 data 为空"""
        response = {'data': []}

        is_valid, error = self.driver._validate_submit_response(response)

        self.assertFalse(is_valid)
        self.assertIn('空', error)

    def test_validate_submit_response_missing_url(self):
        """测试验证响应缺少 url 字段"""
        response = {
            'data': [{'size': '2048x2048'}]
        }

        is_valid, error = self.driver._validate_submit_response(response)

        self.assertFalse(is_valid)
        self.assertIn('url', error)

    def test_validate_submit_response_api_error(self):
        """测试验证 API 错误响应"""
        response = {
            'error': {
                'code': 'InvalidAPIKey',
                'message': 'Invalid API key'
            }
        }

        is_valid, error = self.driver._validate_submit_response(response)

        self.assertFalse(is_valid)
        self.assertIn('API 错误', error)


if __name__ == '__main__':
    import unittest
    unittest.main()
