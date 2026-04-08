"""
QwenMultiAngle RunningHub v1 驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖
"""
import sys
import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

# Mock 外部依赖（必须在 import driver 之前）
sys.modules['utils.sentry_util'] = MagicMock()
sys.modules['utils.file_storage'] = MagicMock()
sys.modules['qiniu'] = MagicMock()

import unittest
from task.visual_drivers.qwen_multi_angle_runninghub_v1_driver import QwenMultiAngleRunninghubV1Driver


def _create_driver():
    """创建驱动实例（mock 所有外部依赖）"""
    with patch('task.visual_drivers.qwen_multi_angle_runninghub_v1_driver.get_dynamic_config_value',
               return_value='test_value'), \
         patch('task.visual_drivers.qwen_multi_angle_runninghub_v1_driver.get_config',
               return_value={}):
        driver = QwenMultiAngleRunninghubV1Driver()
        return driver


def _make_ai_tool(image_path='http://example.com/test.jpg', extra_config=None):
    """创建模拟的 ai_tool 对象"""
    tool = MagicMock()
    tool.id = 1001
    tool.image_path = image_path
    tool.extra_config = extra_config
    return tool


class TestParseExtraConfig(unittest.TestCase):
    """测试 _parse_extra_config 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_parse_valid_json_string(self):
        """正常 JSON 字符串解析"""
        tool = _make_ai_tool(extra_config='{"horizontal_angle": 90, "vertical_angle": 30, "zoom": 7.0}')
        result = self.driver._parse_extra_config(tool)
        self.assertEqual(result['horizontal_angle'], 90)
        self.assertEqual(result['vertical_angle'], 30)
        self.assertEqual(result['zoom'], 7.0)

    def test_parse_dict_input(self):
        """直接传入 dict 类型"""
        tool = _make_ai_tool(extra_config={"horizontal_angle": 180, "zoom": 3.0})
        result = self.driver._parse_extra_config(tool)
        self.assertEqual(result['horizontal_angle'], 180)
        self.assertEqual(result['zoom'], 3.0)

    def test_parse_none_extra_config(self):
        """extra_config 为 None"""
        tool = _make_ai_tool(extra_config=None)
        result = self.driver._parse_extra_config(tool)
        self.assertEqual(result, {})

    def test_parse_empty_string(self):
        """extra_config 为空字符串"""
        tool = _make_ai_tool(extra_config='')
        result = self.driver._parse_extra_config(tool)
        self.assertEqual(result, {})

    def test_parse_invalid_json(self):
        """无效 JSON 字符串"""
        tool = _make_ai_tool(extra_config='not a json')
        result = self.driver._parse_extra_config(tool)
        self.assertEqual(result, {})

    def test_parse_non_dict_json(self):
        """JSON 解析为非 dict 类型（如数组）"""
        tool = _make_ai_tool(extra_config='[1, 2, 3]')
        result = self.driver._parse_extra_config(tool)
        self.assertEqual(result, {})


class TestScaleDimensions(unittest.TestCase):
    """测试 _scale_dimensions 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_no_scaling_needed(self):
        """小尺寸不需要缩放"""
        w, h = self.driver._scale_dimensions(1408, 768, max_dim=1920)
        self.assertEqual(w, 1408)
        self.assertEqual(h, 768)

    def test_no_scaling_at_boundary(self):
        """恰好等于 max_dim 不需要缩放"""
        w, h = self.driver._scale_dimensions(1920, 1080, max_dim=1920)
        self.assertEqual(w, 1920)
        self.assertEqual(h, 1080)

    def test_scale_width_exceeds(self):
        """宽度超过 max_dim，按比例缩放"""
        w, h = self.driver._scale_dimensions(3840, 2160, max_dim=1920)
        self.assertEqual(w, 1920)
        self.assertEqual(h, 1080)

    def test_scale_height_exceeds(self):
        """高度超过 max_dim，按比例缩放"""
        w, h = self.driver._scale_dimensions(1000, 4000, max_dim=1920)
        self.assertEqual(h, 1920)
        # 1000 * (1920/4000) = 480
        self.assertEqual(w, 480)

    def test_scale_produces_even_numbers(self):
        """缩放结果应为偶数"""
        w, h = self.driver._scale_dimensions(1000, 1999, max_dim=1920)
        self.assertEqual(w % 2, 0, f"width {w} should be even")
        self.assertEqual(h % 2, 0, f"height {h} should be even")

    def test_scale_square_large(self):
        """正方形大图缩放"""
        w, h = self.driver._scale_dimensions(4000, 4000, max_dim=1920)
        self.assertEqual(w, 1920)
        self.assertEqual(h, 1920)

    def test_custom_max_dim(self):
        """自定义 max_dim"""
        w, h = self.driver._scale_dimensions(2000, 1000, max_dim=1000)
        self.assertEqual(w, 1000)
        self.assertEqual(h, 500)


class TestGetImageDimensionsFromUrl(unittest.TestCase):
    """测试 _get_image_dimensions_from_url 方法"""

    def setUp(self):
        self.driver = _create_driver()

    @patch('task.visual_drivers.qwen_multi_angle_runninghub_v1_driver.requests.get')
    @patch('task.visual_drivers.qwen_multi_angle_runninghub_v1_driver.Image.open')
    def test_success(self, mock_image_open, mock_get):
        """成功获取图片尺寸"""
        mock_response = MagicMock()
        mock_response.content = b'fake_image_data'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        mock_img = MagicMock()
        mock_img.size = (1920, 1080)
        mock_image_open.return_value = mock_img

        result = self.driver._get_image_dimensions_from_url('http://example.com/test.jpg')
        self.assertEqual(result, (1920, 1080))

    @patch('task.visual_drivers.qwen_multi_angle_runninghub_v1_driver.requests.get')
    def test_network_error(self, mock_get):
        """网络错误返回 None"""
        mock_get.side_effect = Exception("Network error")
        result = self.driver._get_image_dimensions_from_url('http://example.com/test.jpg')
        self.assertIsNone(result)

    @patch('task.visual_drivers.qwen_multi_angle_runninghub_v1_driver.requests.get')
    @patch('task.visual_drivers.qwen_multi_angle_runninghub_v1_driver.Image.open')
    def test_invalid_image(self, mock_image_open, mock_get):
        """无效图片数据返回 None"""
        mock_response = MagicMock()
        mock_response.content = b'not_an_image'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        mock_image_open.side_effect = Exception("Cannot identify image file")
        result = self.driver._get_image_dimensions_from_url('http://example.com/test.jpg')
        self.assertIsNone(result)


class TestValidateSubmitResponse(unittest.TestCase):
    """测试 _validate_submit_response 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_valid_response(self):
        """正确格式的响应"""
        result = {"taskId": "12345", "status": "RUNNING", "errorCode": "", "errorMessage": ""}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_missing_task_id(self):
        """缺少 taskId"""
        result = {"status": "RUNNING"}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertFalse(is_valid)
        self.assertIn('taskId', error)

    def test_missing_status(self):
        """缺少 status"""
        result = {"taskId": "12345"}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertFalse(is_valid)
        self.assertIn('status', error)

    def test_non_dict_response(self):
        """非 dict 类型"""
        is_valid, error = self.driver._validate_submit_response("not a dict")
        self.assertFalse(is_valid)
        self.assertIn('字典', error)

    def test_empty_dict(self):
        """空 dict"""
        is_valid, error = self.driver._validate_submit_response({})
        self.assertFalse(is_valid)
        self.assertIn('taskId', error)


class TestBuildCreateRequest(unittest.TestCase):
    """测试 build_create_request 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def _run_async(self, coro):
        """运行异步方法"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_basic_request_with_extra_config(self):
        """带完整 extra_config 的请求构建"""
        extra_config = json.dumps({
            "horizontal_angle": 90,
            "vertical_angle": 30,
            "zoom": 7.0,
            "width": 1408,
            "height": 768
        })
        tool = _make_ai_tool(extra_config=extra_config)

        # Mock storage.upload_file
        upload_result = MagicMock()
        upload_result.success = True
        upload_result.url = 'http://cdn.example.com/uploaded.jpg'
        upload_result.key = 'key123'
        self.driver._storage.upload_file = AsyncMock(return_value=upload_result)

        result = self._run_async(self.driver.build_create_request(tool))

        # 验证 URL
        self.assertIn('/openapi/v2/run/ai-app/', result['url'])
        self.assertEqual(result['method'], 'POST')

        # 验证 nodeInfoList
        node_list = result['json']['nodeInfoList']
        self.assertEqual(len(node_list), 6)

        # 验证图片节点
        image_node = next(n for n in node_list if n['fieldName'] == 'image')
        self.assertEqual(image_node['fieldValue'], 'http://cdn.example.com/uploaded.jpg')

        # 验证角度参数
        ha_node = next(n for n in node_list if n['fieldName'] == 'horizontal_angle')
        self.assertEqual(ha_node['fieldValue'], '90')

        va_node = next(n for n in node_list if n['fieldName'] == 'vertical_angle')
        self.assertEqual(va_node['fieldValue'], '30')

        zoom_node = next(n for n in node_list if n['fieldName'] == 'zoom')
        self.assertEqual(zoom_node['fieldValue'], '7.0')

        # 验证尺寸
        width_node = next(n for n in node_list if n['fieldName'] == 'width')
        self.assertEqual(width_node['fieldValue'], '1408')

        height_node = next(n for n in node_list if n['fieldName'] == 'height')
        self.assertEqual(height_node['fieldValue'], '768')

    def test_request_no_image_path(self):
        """缺少图片路径应抛出 ValueError"""
        tool = _make_ai_tool(image_path=None)

        with self.assertRaises(ValueError) as ctx:
            self._run_async(self.driver.build_create_request(tool))
        self.assertIn('输入图片', str(ctx.exception))

    def test_request_default_dimensions(self):
        """无 width/height 时使用默认值 1408x768"""
        extra_config = json.dumps({"horizontal_angle": 0, "vertical_angle": 0, "zoom": 5.0})
        tool = _make_ai_tool(extra_config=extra_config)

        upload_result = MagicMock()
        upload_result.success = True
        upload_result.url = 'http://cdn.example.com/uploaded.jpg'
        upload_result.key = 'key123'
        self.driver._storage.upload_file = AsyncMock(return_value=upload_result)

        # Mock _get_image_dimensions_from_url 返回 None（模拟获取失败）
        self.driver._get_image_dimensions_from_url = MagicMock(return_value=None)

        result = self._run_async(self.driver.build_create_request(tool))

        node_list = result['json']['nodeInfoList']
        width_node = next(n for n in node_list if n['fieldName'] == 'width')
        height_node = next(n for n in node_list if n['fieldName'] == 'height')
        self.assertEqual(width_node['fieldValue'], '1408')
        self.assertEqual(height_node['fieldValue'], '768')

    def test_request_auto_scale_large_dimensions(self):
        """大尺寸自动缩放"""
        extra_config = json.dumps({
            "horizontal_angle": 0,
            "vertical_angle": 0,
            "zoom": 5.0,
            "width": 3840,
            "height": 2160
        })
        tool = _make_ai_tool(extra_config=extra_config)

        upload_result = MagicMock()
        upload_result.success = True
        upload_result.url = 'http://cdn.example.com/uploaded.jpg'
        upload_result.key = 'key123'
        self.driver._storage.upload_file = AsyncMock(return_value=upload_result)

        result = self._run_async(self.driver.build_create_request(tool))

        node_list = result['json']['nodeInfoList']
        width_node = next(n for n in node_list if n['fieldName'] == 'width')
        height_node = next(n for n in node_list if n['fieldName'] == 'height')
        # 3840x2160 应缩放到 1920x1080
        self.assertEqual(width_node['fieldValue'], '1920')
        self.assertEqual(height_node['fieldValue'], '1080')

    def test_request_dimensions_from_image_url(self):
        """从图片 URL 自动获取尺寸"""
        extra_config = json.dumps({"horizontal_angle": 45, "vertical_angle": 15, "zoom": 3.0})
        tool = _make_ai_tool(extra_config=extra_config)

        upload_result = MagicMock()
        upload_result.success = True
        upload_result.url = 'http://cdn.example.com/uploaded.jpg'
        upload_result.key = 'key123'
        self.driver._storage.upload_file = AsyncMock(return_value=upload_result)

        # Mock 从图片获取尺寸
        self.driver._get_image_dimensions_from_url = MagicMock(return_value=(2560, 1440))

        result = self._run_async(self.driver.build_create_request(tool))

        node_list = result['json']['nodeInfoList']
        width_node = next(n for n in node_list if n['fieldName'] == 'width')
        height_node = next(n for n in node_list if n['fieldName'] == 'height')
        # 2560x1440 > 1920，应缩放到 1920x1080
        self.assertEqual(width_node['fieldValue'], '1920')
        self.assertEqual(height_node['fieldValue'], '1080')

    def test_request_upload_fallback_to_key(self):
        """上传成功但无 url 时使用 key"""
        tool = _make_ai_tool(extra_config='{"horizontal_angle": 0, "vertical_angle": 0, "zoom": 5.0}')

        upload_result = MagicMock()
        upload_result.success = True
        upload_result.url = None
        upload_result.key = 'storage_key_123'
        self.driver._storage.upload_file = AsyncMock(return_value=upload_result)
        self.driver._get_image_dimensions_from_url = MagicMock(return_value=None)

        result = self._run_async(self.driver.build_create_request(tool))

        node_list = result['json']['nodeInfoList']
        image_node = next(n for n in node_list if n['fieldName'] == 'image')
        self.assertEqual(image_node['fieldValue'], 'storage_key_123')

    def test_request_upload_failure_uses_original_path(self):
        """上传失败时仍使用原始路径"""
        tool = _make_ai_tool(extra_config='{"horizontal_angle": 0, "vertical_angle": 0, "zoom": 5.0}')

        upload_result = MagicMock()
        upload_result.success = False
        upload_result.error = 'Upload failed'
        self.driver._storage.upload_file = AsyncMock(return_value=upload_result)
        self.driver._get_image_dimensions_from_url = MagicMock(return_value=None)

        result = self._run_async(self.driver.build_create_request(tool))

        node_list = result['json']['nodeInfoList']
        image_node = next(n for n in node_list if n['fieldName'] == 'image')
        self.assertEqual(image_node['fieldValue'], 'http://example.com/test.jpg')


class TestBuildCheckQuery(unittest.TestCase):
    """测试 build_check_query 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_check_query_structure(self):
        """检查查询请求结构"""
        result = self.driver.build_check_query('task_12345')
        self.assertIn('/task/openapi/status', result['url'])
        self.assertEqual(result['method'], 'POST')
        self.assertEqual(result['json']['taskId'], 'task_12345')
        self.assertIn('apiKey', result['json'])


class TestCheckStatus(unittest.TestCase):
    """测试 check_status 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_success_status(self):
        """任务成功状态"""
        self.driver._request = MagicMock(side_effect=[
            {"code": 0, "data": "SUCCESS"},
            {"code": 0, "data": [{"fileUrl": "http://cdn.example.com/result.jpg"}]}
        ])

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'http://cdn.example.com/result.jpg')

    def test_failed_status(self):
        """任务失败状态"""
        self.driver._request = MagicMock(return_value={"code": 0, "data": "FAILED"})

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'FAILED')

    def test_running_status(self):
        """任务运行中状态"""
        self.driver._request = MagicMock(return_value={"code": 0, "data": "RUNNING"})

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'RUNNING')

    def test_network_error_returns_running(self):
        """网络错误返回 RUNNING（允许重试）"""
        self.driver._request = MagicMock(side_effect=ConnectionError("timeout"))

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'RUNNING')

    def test_invalid_response_returns_failed(self):
        """无效响应格式返回 FAILED"""
        self.driver._request = MagicMock(return_value="not a dict")

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'FAILED')

    def test_api_error_code(self):
        """API 返回错误码"""
        self.driver._request = MagicMock(return_value={"code": 1, "msg": "Invalid task"})

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error'], 'Invalid task')


if __name__ == '__main__':
    unittest.main()
