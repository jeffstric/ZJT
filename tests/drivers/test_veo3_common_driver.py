"""
Veo3CommonV1 驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

测试结构：
- Veo3CommonV1Driver 基类测试
- Veo3CommonSite1V1Driver ~ Site5V1Driver 站点类测试
"""
import json
import sys
import unittest
from unittest.mock import patch, MagicMock

# Mock 外部依赖（必须在 import driver 之前）
sys.modules['utils.sentry_util'] = MagicMock()
sys.modules['utils.image_upload_utils'] = MagicMock()


def _create_common_driver(site_id='site_1', api_key='test_api_key', base_url='https://yunwu.ai'):
    """创建 Veo3CommonV1Driver 实例（mock 所有外部依赖）"""
    from task.visual_drivers.veo3_common_v1_driver import Veo3CommonV1Driver

    with patch('task.visual_drivers.veo3_common_v1_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.veo3_common_v1_driver.get_config', return_value={}):

        def side_effect(*keys, default=None):
            key_map = {
                ('api_aggregator', site_id, 'api_key'): api_key,
                ('api_aggregator', site_id, 'base_url'): base_url,
                ('api_aggregator', site_id, 'name'): f'测试站点{site_id}',
                ('timeout', 'request_timeout'): 30,
                ('server', 'is_local'): False,
            }
            return key_map.get(keys, default)

        mock_config.side_effect = side_effect
        driver = Veo3CommonV1Driver(site_id=site_id)
        return driver


def _create_site_driver(site_id):
    """创建站点驱动实例"""
    from task.visual_drivers.veo3_common_v1_driver import (
        Veo3CommonSite1V1Driver,
        Veo3CommonSite2V1Driver,
        Veo3CommonSite3V1Driver,
        Veo3CommonSite4V1Driver,
        Veo3CommonSite5V1Driver
    )

    site_driver_map = {
        'site_1': Veo3CommonSite1V1Driver,
        'site_2': Veo3CommonSite2V1Driver,
        'site_3': Veo3CommonSite3V1Driver,
        'site_4': Veo3CommonSite4V1Driver,
        'site_5': Veo3CommonSite5V1Driver,
    }

    driver_class = site_driver_map.get(site_id)
    if not driver_class:
        raise ValueError(f"Unknown site_id: {site_id}")

    with patch('task.visual_drivers.veo3_common_v1_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.veo3_common_v1_driver.get_config', return_value={}):

        def side_effect(*keys, default=None):
            key_map = {
                ('api_aggregator', site_id, 'api_key'): 'test_api_key',
                ('api_aggregator', site_id, 'base_url'): 'https://yunwu.ai',
                ('api_aggregator', site_id, 'name'): f'测试站点{site_id}',
                ('timeout', 'request_timeout'): 30,
                ('server', 'is_local'): False,
            }
            return key_map.get(keys, default)

        mock_config.side_effect = side_effect
        return driver_class()


def _make_ai_tool(prompt='测试提示词', image_path='http://example.com/test.jpg',
                  extra_config=None, ratio='9:16', reference_images=None):
    """创建模拟的 ai_tool 对象"""
    tool = MagicMock()
    tool.id = 1001
    tool.prompt = prompt
    tool.image_path = image_path
    tool.extra_config = extra_config
    tool.ratio = ratio
    tool.reference_images = reference_images
    return tool


class TestVeo3CommonV1Driver(unittest.TestCase):
    """测试 Veo3CommonV1Driver 基类"""

    def test_driver_name_contains_site_id(self):
        """驱动名称应包含站点ID"""
        driver = _create_common_driver(site_id='site_3')
        self.assertIn('site_3', driver.driver_name)

    def test_base_url_config(self):
        """验证 base_url 配置"""
        custom_url = 'https://custom.yunwu.ai'
        driver = _create_common_driver(site_id='site_2', base_url=custom_url)
        self.assertEqual(driver._base_url, custom_url)

    def test_api_key_config(self):
        """验证 api_key 配置"""
        custom_key = 'custom_api_key_123'
        driver = _create_common_driver(site_id='site_4', api_key=custom_key)
        self.assertEqual(driver._api_key, custom_key)


class TestValidateSubmitResponse(unittest.TestCase):
    """测试 _validate_submit_response 方法"""

    def setUp(self):
        self.driver = _create_common_driver()

    def test_valid_response_with_id(self):
        """正确格式的响应（有 id 字段）"""
        result = {"id": "chatcmpl-12345", "object": "video.completion", "created": 1234567890}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_missing_id_field(self):
        """缺少 id 字段"""
        result = {"status": "processing"}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertFalse(is_valid)
        self.assertIn("id", error)

    def test_non_dict_response(self):
        """非 dict 类型"""
        is_valid, error = self.driver._validate_submit_response("not a dict")
        self.assertFalse(is_valid)
        self.assertIn("字典", error)

    def test_empty_dict(self):
        """空 dict"""
        is_valid, error = self.driver._validate_submit_response({})
        self.assertFalse(is_valid)
        self.assertIn("id", error)

    def test_id_not_string(self):
        """id 字段类型错误（非 str）"""
        result = {"id": 12345}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertFalse(is_valid)
        self.assertIn("str", error)


class TestValidateStatusResponse(unittest.TestCase):
    """测试 _validate_status_response 方法"""

    def setUp(self):
        self.driver = _create_common_driver()

    def test_valid_response_with_id(self):
        """正确格式的响应（有 id 字段）"""
        result = {"id": "chatcmpl-12345", "status": "completed"}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_missing_id_field(self):
        """缺少 id 字段"""
        result = {"status": "processing"}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertFalse(is_valid)
        self.assertIn("id", error)

    def test_non_dict_response(self):
        """非 dict 类型"""
        is_valid, error = self.driver._validate_status_response(["not", "a", "dict"])
        self.assertFalse(is_valid)
        self.assertIn("字典", error)


class TestBuildCreateRequest(unittest.TestCase):
    """测试 build_create_request 方法"""

    def setUp(self):
        self.driver = _create_common_driver()

    def test_basic_request_structure(self):
        """基本请求结构验证"""
        tool = _make_ai_tool()
        result = self.driver.build_create_request(tool)

        # 验证 URL
        self.assertIn('/v1/video/create', result['url'])
        self.assertEqual(result['method'], 'POST')

        # 验证 headers
        self.assertIn('Authorization', result['headers'])
        self.assertEqual(result['headers']['Content-Type'], 'application/json')

        # 验证 payload
        self.assertEqual(result['json']['model'], 'veo3.1-fast')
        self.assertEqual(result['json']['prompt'], '测试提示词')
        self.assertEqual(result['json']['enhance_prompt'], True)
        self.assertEqual(result['json']['images'], ['http://example.com/test.jpg'])

    def test_request_without_image(self):
        """无图片时的请求"""
        tool = _make_ai_tool(image_path=None)
        result = self.driver.build_create_request(tool)

        self.assertNotIn('images', result['json'])

    def test_request_with_first_last_frame(self):
        """首尾帧模式 - image_path 用逗号分隔"""
        tool = _make_ai_tool(
            image_path='http://example.com/first.jpg,http://example.com/last.jpg'
        )
        result = self.driver.build_create_request(tool)

        self.assertEqual(result['json']['images'], [
            'http://example.com/first.jpg',
            'http://example.com/last.jpg'
        ])

    def test_request_with_multi_reference(self):
        """多参考图模式"""
        tool = _make_ai_tool(
            image_path=None,
            extra_config='{"image_mode": "multi_reference"}',
            reference_images=[
                'http://example.com/ref1.jpg',
                'http://example.com/ref2.jpg',
                'http://example.com/ref3.jpg'
            ]
        )
        result = self.driver.build_create_request(tool)

        self.assertEqual(result['json']['images'], [
            'http://example.com/ref1.jpg',
            'http://example.com/ref2.jpg',
            'http://example.com/ref3.jpg'
        ])

    def test_request_with_extra_reference_images_truncated(self):
        """超过3张参考图时截取前3张"""
        tool = _make_ai_tool(
            image_path=None,
            extra_config='{"image_mode": "multi_reference"}',
            reference_images=[
                'http://example.com/ref1.jpg',
                'http://example.com/ref2.jpg',
                'http://example.com/ref3.jpg',
                'http://example.com/ref4.jpg',
                'http://example.com/ref5.jpg'
            ]
        )
        result = self.driver.build_create_request(tool)

        self.assertEqual(len(result['json']['images']), 3)
        self.assertEqual(result['json']['images'][0], 'http://example.com/ref1.jpg')
        self.assertEqual(result['json']['images'][2], 'http://example.com/ref3.jpg')


class TestBuildCheckQuery(unittest.TestCase):
    """测试 build_check_query 方法"""

    def setUp(self):
        self.driver = _create_common_driver()

    def test_check_query_structure(self):
        """检查查询请求结构"""
        result = self.driver.build_check_query('task_12345')

        self.assertIn('/v1/video/query', result['url'])
        self.assertEqual(result['method'], 'GET')
        self.assertEqual(result['params'], {'id': 'task_12345'})
        self.assertIsNone(result['json'])
        self.assertIn('Authorization', result['headers'])

    def test_check_query_with_project_id(self):
        """带 project_id 的查询"""
        result = self.driver.build_check_query('veo3_project_abc')

        self.assertEqual(result['params'], {'id': 'veo3_project_abc'})


class TestSubmitTask(unittest.TestCase):
    """测试 submit_task 方法"""

    def setUp(self):
        self.driver = _create_common_driver()

    def test_submit_task_success(self):
        """提交任务成功"""
        tool = _make_ai_tool()
        self.driver._request = MagicMock(return_value={"id": "veo3_task_123"})

        result = self.driver.submit_task(tool)

        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'veo3_task_123')

    def test_submit_task_invalid_response(self):
        """提交任务 - 无效响应格式"""
        tool = _make_ai_tool()
        self.driver._request = MagicMock(return_value={"error": "invalid"})

        result = self.driver.submit_task(tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'SYSTEM')

    def test_submit_task_network_error(self):
        """提交任务 - 网络错误"""
        tool = _make_ai_tool()
        self.driver._request = MagicMock(side_effect=ConnectionError('timeout'))

        result = self.driver.submit_task(tool)

        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])

    def test_submit_task_request_called(self):
        """提交任务 - 验证 _request 被正确调用"""
        tool = _make_ai_tool(prompt='测试提示词')
        self.driver._request = MagicMock(return_value={"id": "task_123"})

        self.driver.submit_task(tool)

        self.driver._request.assert_called_once()
        call_args = self.driver._request.call_args
        self.assertIn('/v1/video/create', call_args.kwargs['url'])
        self.assertEqual(call_args.kwargs['method'], 'POST')


class TestCheckStatus(unittest.TestCase):
    """测试 check_status 方法"""

    def setUp(self):
        self.driver = _create_common_driver()

    def test_check_status_completed(self):
        """任务完成状态 - output.video.url 格式"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "status": "completed",
            "output": {
                "video": {"url": "https://example.com/result.mp4"}
            }
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result.mp4')

    def test_check_status_completed_data_video_url(self):
        """任务完成状态 - data.video.url 格式"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "status": "completed",
            "data": {
                "video": {"url": "https://example.com/result.mp4"}
            }
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result.mp4')

    def test_check_status_completed_data_media_url(self):
        """任务完成状态 - data.mediaUrl 格式"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "status": "completed",
            "data": {
                "mediaUrl": "https://example.com/result.mp4"
            }
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result.mp4')

    def test_check_status_completed_direct_video_url(self):
        """任务完成状态 - 直接 video.url 格式"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "status": "completed",
            "video": {"url": "https://example.com/result.mp4"}
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result.mp4')

    def test_check_status_completed_choices_content(self):
        """任务完成状态 - choices.message.content 格式"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "choices": [{
                "message": {"content": "https://example.com/result.mp4"},
                "finish_reason": "stop"
            }]
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result.mp4')

    def test_check_status_completed_detail_video_url(self):
        """任务完成状态 - detail.video_url 格式"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "status": "completed",
            "detail": {
                "status": "completed",
                "video_url": "https://example.com/result.mp4"
            }
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result.mp4')

    def test_check_status_completed_root_video_url(self):
        """任务完成状态 - 根级别 video_url 格式"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "status": "completed",
            "video_url": "https://example.com/result.mp4"
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://example.com/result.mp4')

    def test_check_status_failed(self):
        """任务失败状态"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "status": "failed",
            "error": "内容违规"
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error'], '内容违规')

    def test_check_status_processing(self):
        """任务处理中状态"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "status": "processing"
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'RUNNING')

    def test_check_status_in_queue(self):
        """任务排队中状态"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "status": "in_queue"
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'RUNNING')

    def test_check_status_network_error(self):
        """网络错误返回 RUNNING"""
        self.driver._request = MagicMock(side_effect=ConnectionError('timeout'))

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'RUNNING')

    def test_check_status_invalid_response(self):
        """无效响应格式返回 FAILED"""
        self.driver._request = MagicMock(return_value="not a dict")

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'FAILED')

    def test_check_status_completed_no_video_url(self):
        """任务完成但无视频URL"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "status": "completed",
            "output": {}
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('未找到视频', result['error'])

    def test_check_status_timeout_error(self):
        """超时错误返回 RUNNING"""
        self.driver._request = MagicMock(side_effect=TimeoutError('request timeout'))

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'RUNNING')

    def test_check_status_http_error(self):
        """HTTP 错误（如 404）返回 FAILED"""
        from requests import HTTPError
        self.driver._request = MagicMock(side_effect=HTTPError('404 Client Error'))

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error_type'], 'SYSTEM')

    def test_check_status_empty_status_no_choices(self):
        """status 为空且无 choices 时返回 RUNNING"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123"
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'RUNNING')

    def test_check_status_choices_unfinished(self):
        """choices 存在但 finish_reason 为空时返回 RUNNING"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "choices": [{"message": {"content": ""}, "finish_reason": ""}]
        })

        result = self.driver.check_status('task_123')

        self.assertEqual(result['status'], 'RUNNING')

    def test_check_status_request_called_with_params(self):
        """验证 check_status 调用 _request 时传入正确的 query params"""
        self.driver._request = MagicMock(return_value={
            "id": "task_123",
            "status": "processing"
        })

        self.driver.check_status('task_123')

        self.driver._request.assert_called_once()
        call_args = self.driver._request.call_args
        self.assertIn('/v1/video/query', call_args.kwargs['url'])
        self.assertEqual(call_args.kwargs['method'], 'GET')
        self.assertEqual(call_args.kwargs['params'], {'id': 'task_123'})


class TestExtractVideoUrl(unittest.TestCase):
    """测试 _extract_video_url 方法"""

    def setUp(self):
        self.driver = _create_common_driver()

    def test_extract_from_detail_video_url(self):
        """从 detail.video_url 提取"""
        data = {
            "detail": {
                "video_url": "https://example.com/video0.mp4"
            }
        }
        result = self.driver._extract_video_url(data)
        self.assertEqual(result, "https://example.com/video0.mp4")

    def test_extract_from_output_video_url(self):
        """从 output.video.url 提取"""
        data = {
            "output": {
                "video": {"url": "https://example.com/video1.mp4"}
            }
        }
        result = self.driver._extract_video_url(data)
        self.assertEqual(result, "https://example.com/video1.mp4")

    def test_extract_from_data_video_url(self):
        """从 data.video.url 提取"""
        data = {
            "data": {
                "video": {"url": "https://example.com/video2.mp4"}
            }
        }
        result = self.driver._extract_video_url(data)
        self.assertEqual(result, "https://example.com/video2.mp4")

    def test_extract_from_data_media_url(self):
        """从 data.mediaUrl 提取"""
        data = {
            "data": {
                "mediaUrl": "https://example.com/video3.mp4"
            }
        }
        result = self.driver._extract_video_url(data)
        self.assertEqual(result, "https://example.com/video3.mp4")

    def test_extract_from_direct_video_url(self):
        """从 direct video.url 提取"""
        data = {
            "video": {"url": "https://example.com/video4.mp4"}
        }
        result = self.driver._extract_video_url(data)
        self.assertEqual(result, "https://example.com/video4.mp4")

    def test_extract_from_choices_content(self):
        """从 choices.message.content 提取"""
        data = {
            "choices": [{
                "message": {"content": "https://example.com/video5.mp4"}
            }]
        }
        result = self.driver._extract_video_url(data)
        self.assertEqual(result, "https://example.com/video5.mp4")

    def test_extract_from_root_video_url(self):
        """从根级别 video_url 提取"""
        data = {
            "video_url": "https://example.com/video6.mp4"
        }
        result = self.driver._extract_video_url(data)
        self.assertEqual(result, "https://example.com/video6.mp4")

    def test_extract_returns_none_when_no_url(self):
        """无 URL 时返回 None"""
        data = {
            "output": {},
            "data": {}
        }
        result = self.driver._extract_video_url(data)
        self.assertIsNone(result)

    def test_extract_from_choices_non_url_content(self):
        """choices.message.content 不是 URL 时返回 None"""
        data = {
            "choices": [{
                "message": {"content": "some text not url"}
            }]
        }
        result = self.driver._extract_video_url(data)
        self.assertIsNone(result)


class TestVeo3CommonSiteDrivers(unittest.TestCase):
    """测试 Veo3CommonSite1V1Driver ~ Site5V1Driver 站点类"""

    def test_site1_driver(self):
        """Site1 驱动"""
        driver = _create_site_driver('site_1')
        self.assertIn('site_1', driver.driver_name)
        self.assertEqual(driver._site_id, 'site_1')

    def test_site2_driver(self):
        """Site2 驱动"""
        driver = _create_site_driver('site_2')
        self.assertIn('site_2', driver.driver_name)
        self.assertEqual(driver._site_id, 'site_2')

    def test_site3_driver(self):
        """Site3 驱动"""
        driver = _create_site_driver('site_3')
        self.assertIn('site_3', driver.driver_name)
        self.assertEqual(driver._site_id, 'site_3')

    def test_site4_driver(self):
        """Site4 驱动"""
        driver = _create_site_driver('site_4')
        self.assertIn('site_4', driver.driver_name)
        self.assertEqual(driver._site_id, 'site_4')

    def test_site5_driver(self):
        """Site5 驱动"""
        driver = _create_site_driver('site_5')
        self.assertIn('site_5', driver.driver_name)
        self.assertEqual(driver._site_id, 'site_5')


if __name__ == '__main__':
    import unittest
    unittest.main()
