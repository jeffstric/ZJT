"""
LTX2.3 RunningHub 驱动数据库集成测试
直接测试驱动方法，不依赖 video_task.py 的业务逻辑
"""
import sys
import asyncio
from dataclasses import dataclass
from unittest.mock import patch, MagicMock, AsyncMock

# Mock 第三方依赖模块
sys.modules['utils.sentry_util'] = MagicMock()
sys.modules['utils.file_storage'] = MagicMock()
sys.modules['qiniu'] = MagicMock()
sys.modules['aiofiles'] = MagicMock()
sys.modules['requests'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['PIL.Image'] = MagicMock()

from tests.base_video_driver_test import BaseVideoDriverTest, mock_get_dynamic_config_value
from task.visual_drivers.ltx2_3_runninghub_v1_driver import Ltx2Dot3RunninghubV1Driver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING, AI_TOOL_STATUS_COMPLETED, AI_TOOL_STATUS_FAILED

LTX2_3_IMAGE_TO_VIDEO_TYPE = 10


@dataclass
class MockUploadResult:
    """Mock 上传结果"""
    success: bool = True
    key: str = ""
    hash: str = ""
    url: str = ""
    error: str = ""


def create_mock_upload_result(key: str, image_path: str) -> MockUploadResult:
    """创建 mock 上传结果 - 公网 URL 直接返回原路径"""
    return MockUploadResult(success=True, key=image_path, url=image_path)


class TestLtx2Dot3RunninghubWithDB(BaseVideoDriverTest):
    """LTX2.3 驱动数据库集成测试"""

    def setUp(self):
        """测试前准备"""
        super().setUp()
        # 使用统一的 mock 配置函数，从 config_unit.yml 获取配置
        with patch('task.visual_drivers.ltx2_3_runninghub_v1_driver.get_dynamic_config_value', side_effect=mock_get_dynamic_config_value):
            self.driver = Ltx2Dot3RunninghubV1Driver()
            # Mock _storage.upload_file 为异步方法
            self.driver._storage.upload_file = AsyncMock(side_effect=create_mock_upload_result)

    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'ltx2.3_runninghub_v1')
        self.assertEqual(self.driver.driver_type, LTX2_3_IMAGE_TO_VIDEO_TYPE)
        self.assertEqual(self.driver._webapp_id, '2038246514870460418')

    def test_validate_submit_response(self):
        """测试提交响应验证"""
        # 有效响应
        valid_response = {
            "taskId": "123456",
            "status": "RUNNING",
            "errorCode": "",
            "errorMessage": ""
        }
        is_valid, error = self.driver._validate_submit_response(valid_response)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

        # 无 taskId
        invalid_response = {"status": "RUNNING"}
        is_valid, error = self.driver._validate_submit_response(invalid_response)
        self.assertFalse(is_valid)
        self.assertIn("taskId", error)

        # 无 status
        invalid_response = {"taskId": "123"}
        is_valid, error = self.driver._validate_submit_response(invalid_response)
        self.assertFalse(is_valid)
        self.assertIn("status", error)

        # 非字典类型
        is_valid, error = self.driver._validate_submit_response("not a dict")
        self.assertFalse(is_valid)
        self.assertIn("字典类型", error)

    def test_calculate_frame_count(self):
        """测试帧数计算（必须为8的倍数+1）"""
        test_cases = [
            (5, 121),   # 5秒 -> 121帧
            (8, 193),   # 8秒 -> 193帧
            (10, 241),  # 10秒 -> 241帧
            (2, 49),    # 2秒 -> 49帧
        ]

        for duration, expected in test_cases:
            result = self.driver._calculate_frame_count(duration)
            # 验证必须是 8 的倍数 + 1
            self.assertEqual((result - 1) % 8, 0, f"duration={duration}, result={result} 不是 8 的倍数 + 1")
            # 验证结果合理（基于约 24fps）
            self.assertGreater(result, duration * 20)
            self.assertLess(result, duration * 30)

    def test_get_image_dimensions_with_mock(self):
        """测试获取图片尺寸（mock 依赖）"""
        with patch('task.visual_drivers.ltx2_3_runninghub_v1_driver.resolve_url_to_local_file_sync') as mock_resolve:
            # Mock 返回本地文件路径
            mock_resolve.return_value = "/fake/local/path/image.jpg"

            with patch('PIL.Image.open') as mock_image_open:
                mock_img = MagicMock()
                mock_img.size = (1920, 1080)
                mock_image_open.return_value = mock_img

                width, height = self.driver._get_image_dimensions("https://example.com/image.jpg")

                self.assertEqual(width, 1920)
                self.assertEqual(height, 1080)
                mock_resolve.assert_called_once()

    def test_get_image_dimensions_with_invalid_path(self):
        """测试获取图片尺寸失败时返回默认尺寸"""
        with patch('task.visual_drivers.ltx2_3_runninghub_v1_driver.resolve_url_to_local_file_sync') as mock_resolve:
            # Mock 返回 None（解析失败）
            mock_resolve.return_value = None

            width, height = self.driver._get_image_dimensions("https://invalid.url/image.jpg")

            # 应该返回默认尺寸
            self.assertEqual(width, 1280)
            self.assertEqual(height, 720)

    def test_build_create_request(self):
        """测试构建创建任务请求参数"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=LTX2_3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试提示词',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)

        with patch.object(self.driver, '_get_image_dimensions') as mock_dimensions:
            mock_dimensions.return_value = (1920, 1080)

            req = asyncio.run(self.driver.build_create_request(tool))

        # 验证 url
        self.assertIn('/openapi/v2/run/ai-app/', req['url'])
        self.assertIn('2038246514870460418', req['url'])  # webapp_id

        # 验证 method
        self.assertEqual(req['method'], 'POST')

        # 验证 json 结构
        self.assertIn('nodeInfoList', req['json'])
        self.assertIsInstance(req['json']['nodeInfoList'], list)
        self.assertEqual(req['json']['instanceType'], 'default')  # LTX2.3 使用 default
        self.assertEqual(req['json']['usePersonalQueue'], 'false')

        # 验证 nodeInfoList 包含必要字段
        node_info_list = req['json']['nodeInfoList']

        # 查找关键节点
        image_node = next((n for n in node_info_list if n['fieldName'] == 'image'), None)
        self.assertIsNotNone(image_node)
        self.assertEqual(image_node['nodeId'], '2004')  # LTX2.3 使用 2004

        # 验证视频宽高（最长边限制在 640，等比例缩放）
        # 1920x1080 -> 640x360 (最长边 1920 缩放到 640)
        width_node = next((n for n in node_info_list if n['nodeId'] == '5018'), None)
        self.assertIsNotNone(width_node)
        self.assertEqual(width_node['fieldValue'], '640')  # 1920 * 640/1920

        height_node = next((n for n in node_info_list if n['nodeId'] == '5020'), None)
        self.assertIsNotNone(height_node)
        self.assertEqual(height_node['fieldValue'], '360')  # 1080 * 640/1920

        # 验证帧数节点
        frame_node = next((n for n in node_info_list if n['nodeId'] == '5022'), None)
        self.assertIsNotNone(frame_node)
        # 帧数必须是 8 的倍数 + 1
        frame_value = int(frame_node['fieldValue'])
        self.assertEqual((frame_value - 1) % 8, 0)

        # 验证提示词节点
        prompt_node = next((n for n in node_info_list if n['nodeId'] == '5013'), None)
        self.assertIsNotNone(prompt_node)
        self.assertEqual(prompt_node['fieldValue'], '测试提示词')

        # 验证 headers
        self.assertIn('Authorization', req['headers'])
        self.assertTrue(req['headers']['Authorization'].startswith('Bearer '))
        self.assertEqual(req['headers']['Content-Type'], 'application/json')

    def test_build_check_query(self):
        """测试构建查询状态请求参数"""
        project_id = 'ltx2_3_test_task_123'
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
            ai_tool_type=LTX2_3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试 LTX2.3 提交成功',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PROCESSING
        )

        tool = self.get_ai_tool_from_db(task_id)

        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "taskId": "ltx2_3_task_123",
                "status": "RUNNING",
                "errorCode": "",
                "errorMessage": ""
            }

            result = asyncio.run(self.driver.submit_task(tool))

            # 验证成功
            self.assertTrue(result['success'])
            self.assertEqual(result['project_id'], 'ltx2_3_task_123')

    def test_submit_task_with_error_code(self):
        """测试提交任务返回错误码"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=LTX2_3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试错误',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PROCESSING
        )

        tool = self.get_ai_tool_from_db(task_id)

        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "taskId": "",
                "status": "FAILED",
                "errorCode": "1001",
                "errorMessage": "Invalid request"
            }

            result = asyncio.run(self.driver.submit_task(tool))

            # 验证失败
            self.assertFalse(result['success'])
            self.assertIn('error', result)
            self.assertEqual(result['error_type'], 'USER')
            self.assertFalse(result['retry'])

    def test_submit_task_network_error(self):
        """测试提交任务网络异常"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=LTX2_3_IMAGE_TO_VIDEO_TYPE,
            prompt='测试网络异常',
            image_path='https://example.com/test.jpg',
            duration=5,
            status=AI_TOOL_STATUS_PROCESSING
        )

        tool = self.get_ai_tool_from_db(task_id)

        with patch.object(self.driver, '_request') as mock_req:
            mock_req.side_effect = ConnectionError("Connection refused")

            result = asyncio.run(self.driver.submit_task(tool))

            # 验证网络错误，允许重试
            self.assertFalse(result['success'])
            self.assertEqual(result['error_type'], 'USER')
            self.assertTrue(result['retry'])

    def test_check_status_running(self):
        """测试查询状态 - 任务运行中"""
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "code": 0,
                "data": "RUNNING"
            }

            result = self.driver.check_status('test_task_id')

            self.assertEqual(result['status'], 'RUNNING')
            self.assertIn('message', result)

    def test_check_status_success(self):
        """测试查询状态 - 任务成功"""
        with patch.object(self.driver, '_request') as mock_req:
            # 第一次调用返回 SUCCESS
            mock_req.side_effect = [
                {"code": 0, "data": "SUCCESS"},
                {
                    "code": 0,
                    "data": [
                        {"fileUrl": "https://example.com/video.mp4"}
                    ]
                }
            ]

            result = self.driver.check_status('test_task_id')

            self.assertEqual(result['status'], 'SUCCESS')
            self.assertEqual(result['result_url'], 'https://example.com/video.mp4')

    def test_check_status_failed(self):
        """测试查询状态 - 任务失败"""
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "code": 0,
                "data": "FAILED"
            }

            result = self.driver.check_status('test_task_id')

            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['error_type'], 'USER')

    def test_check_status_api_error(self):
        """测试查询状态 - API 返回错误"""
        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = {
                "code": 1001,
                "msg": "Task not found"
            }

            result = self.driver.check_status('nonexistent_task')

            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['error'], 'Task not found')
            self.assertEqual(result['error_type'], 'USER')
