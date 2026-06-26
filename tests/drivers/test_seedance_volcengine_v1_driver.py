"""
SeedanceVolcengineV1 驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

测试结构：
- SeedanceVolcengineV1Driver 基类测试（初始化、响应验证、请求构建）
- 三种互斥图片模式测试（首尾帧 / 多参考图 / 降级模式）
- 首尾帧 role 字段逻辑测试
- 多参考图模式下参考视频/音频 CDN 上传测试
- submit_task / check_status 测试模式测试
- 子类实例化测试
"""
import json
import sys
import unittest
from unittest.mock import patch, MagicMock, PropertyMock

from model.ai_tool_pipeline_steps import PipelineStepStatus

# Mock 外部依赖（必须在 import driver 之前）
sys.modules['utils.sentry_util'] = MagicMock()
sys.modules['utils.image_upload_utils'] = MagicMock()


def _create_driver(driver_type=21, model_name='doubao-seedance-1-5-pro-251215',
                   api_key='test_api_key', test_mode=False, mock_video_url=None):
    """创建 SeedanceVolcengineV1Driver 实例（mock 所有外部依赖）"""
    from task.visual_drivers.seedance_volcengine_v1_driver import SeedanceVolcengineV1Driver

    with patch('task.visual_drivers.seedance_volcengine_v1_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.seedance_volcengine_v1_driver.get_config', return_value={}):

        def side_effect(*keys, default=None):
            key_map = {
                ('volcengine', 'api_key'): api_key,
                ('timeout', 'request_timeout'): 30,
                ('server', 'is_local'): False,
                ('test_mode', 'enabled'): test_mode,
                ('test_mode', 'mock_videos'): {'image_to_video': mock_video_url} if mock_video_url else {},
            }
            return key_map.get(keys, default)

        mock_config.side_effect = side_effect
        driver = SeedanceVolcengineV1Driver(driver_type=driver_type, model_name=model_name)
        return driver


def _make_ai_tool(prompt='测试提示词', image_path='http://example.com/first.jpg',
                  extra_config=None, duration=5, reference_images=None,
                  audio_path=None, video_path=None, ratio=None):
    """创建模拟的 ai_tool 对象"""
    tool = MagicMock()
    tool.id = 1001
    tool.prompt = prompt
    tool.image_path = image_path
    tool.extra_config = extra_config
    tool.duration = duration
    tool.reference_images = reference_images
    tool.audio_path = audio_path
    tool.video_path = video_path
    tool.ratio = ratio
    return tool


class TestSeedanceDriverInit(unittest.TestCase):
    """测试驱动初始化"""

    def test_default_initialization(self):
        """默认初始化：验证核心属性"""
        driver = _create_driver()
        self.assertEqual(driver.driver_type, 21)
        self.assertEqual(driver._model, 'doubao-seedance-1-5-pro-251215')
        self.assertEqual(driver._api_key, 'test_api_key')
        self.assertEqual(driver._base_url, 'https://ark.cn-beijing.volces.com')
        self.assertFalse(driver._test_mode_enabled)

    def test_test_mode_disabled_by_default(self):
        """测试模式默认关闭"""
        driver = _create_driver(test_mode=False)
        self.assertFalse(driver._test_mode_enabled)
        self.assertIsNone(driver._mock_video_url)

    def test_test_mode_enabled(self):
        """测试模式可启用"""
        driver = _create_driver(test_mode=True, mock_video_url='https://cdn.example.com/mock.mp4')
        self.assertTrue(driver._test_mode_enabled)
        self.assertEqual(driver._mock_video_url, 'https://cdn.example.com/mock.mp4')


class TestValidateSubmitResponse(unittest.TestCase):
    """测试 _validate_submit_response 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_valid_response_with_id(self):
        """正确格式的响应（有 id 字段）"""
        result = {"id": "cgt-20260430-abc123"}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_missing_id_field(self):
        """缺少 id 字段"""
        result = {"status": "processing"}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertFalse(is_valid)
        self.assertIn("id", error)

    def test_error_in_response(self):
        """响应中包含 error 字段"""
        result = {"error": {"code": "RateLimitExceeded", "message": "请求过于频繁"}}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertFalse(is_valid)
        self.assertIn("RateLimitExceeded", error)

    def test_non_dict_response(self):
        """非字典类型的响应"""
        result = "invalid response"
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertFalse(is_valid)
        self.assertIn("字典", error)

    def test_empty_dict(self):
        """空字典"""
        result = {}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertFalse(is_valid)
        self.assertIn("id", error)


class TestValidateStatusResponse(unittest.TestCase):
    """测试 _validate_status_response 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_succeeded_response(self):
        """成功的任务响应"""
        result = {
            "id": "cgt-xxx",
            "status": "succeeded",
            "content": {"video_url": "https://cdn.example.com/result.mp4"}
        }
        is_valid, error = self.driver._validate_status_response(result)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_failed_response(self):
        """失败的任务响应"""
        result = {"id": "cgt-xxx", "status": "failed"}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertTrue(is_valid)

    def test_queued_response(self):
        """排队中的任务响应（新增的 queued 状态）"""
        result = {"id": "cgt-xxx", "status": "queued"}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertTrue(is_valid)

    def test_running_response(self):
        """运行中的任务响应"""
        result = {"id": "cgt-xxx", "status": "running"}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertTrue(is_valid)

    def test_invalid_status(self):
        """无效的 status 值"""
        result = {"id": "cgt-xxx", "status": "pending"}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertFalse(is_valid)
        self.assertIn("pending", error)

    def test_succeeded_without_content(self):
        """成功但缺少 content"""
        result = {"id": "cgt-xxx", "status": "succeeded"}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertFalse(is_valid)
        self.assertIn("content", error)

    def test_succeeded_without_video_url(self):
        """成功但 content 中缺少 video_url（空字典被视为缺少 content）"""
        result = {"id": "cgt-xxx", "status": "succeeded", "content": {}}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertFalse(is_valid)
        # 空字典 {} 被 `not content` 判为 True，返回 "缺少 content 字段"
        self.assertIn("content", error)

    def test_missing_id(self):
        """缺少 id 字段"""
        result = {"status": "running"}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertFalse(is_valid)
        self.assertIn("id", error)

    def test_missing_status(self):
        """缺少 status 字段"""
        result = {"id": "cgt-xxx"}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertFalse(is_valid)
        self.assertIn("status", error)


class TestBuildCheckQuery(unittest.TestCase):
    """测试 build_check_query 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_check_query_structure(self):
        """验证查询请求结构"""
        result = self.driver.build_check_query("cgt-20260430-abc123")
        self.assertEqual(result["method"], "GET")
        self.assertIn("/api/v3/contents/generations/tasks/cgt-20260430-abc123", result["url"])
        self.assertEqual(result["json"], None)
        self.assertIn("Authorization", result["headers"])
        self.assertIn("Bearer test_api_key", result["headers"]["Authorization"])


class TestBuildCreateRequestFirstLastFrame(unittest.TestCase):
    """测试首尾帧模式下的 build_create_request"""

    def setUp(self):
        self.driver = _create_driver()

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_first_frame_only_no_role(self, mock_compress):
        """仅首帧（无尾帧）：image_url 不带 role 字段"""
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_frame'}
        )

        result = self.driver.build_create_request(ai_tool)

        # 找到 image_url 类型的 content 元素
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(len(image_items), 1)
        # 无尾帧时，首帧不带 role 字段
        self.assertNotIn('role', image_items[0])

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_first_and_last_frame_with_roles(self, mock_compress):
        """首尾帧模式：首帧带 role=first_frame，尾帧带 role=last_frame"""
        def side_effect(url, config, max_size_mb=10.0, is_local=True):
            if 'first' in url:
                return (True, 'https://cdn.example.com/first.jpg', None)
            return (True, 'https://cdn.example.com/last.jpg', None)

        mock_compress.side_effect = side_effect
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg,http://example.com/last.jpg',
            extra_config={'image_mode': 'first_last_frame'}
        )

        result = self.driver.build_create_request(ai_tool)

        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(len(image_items), 2)
        self.assertEqual(image_items[0].get('role'), 'first_frame')
        self.assertEqual(image_items[1].get('role'), 'last_frame')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_first_frame_compress_failure(self, mock_compress):
        """首帧图片压缩失败：返回错误"""
        mock_compress.return_value = (False, None, '压缩失败')
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_frame'}
        )

        result = self.driver.build_create_request(ai_tool)
        self.assertFalse(result['success'])
        self.assertIn('首帧图片', result['error'])

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_first_last_frame_no_first_frame(self, mock_compress):
        """首尾帧模式但没有首帧图片：返回错误"""
        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'image_mode': 'first_last_frame'}
        )
        # mock get_all_images_by_mode 返回无首帧
        with patch.object(self.driver, 'get_all_images_by_mode', return_value={
            'mode': 'first_last_frame', 'first_frame': None, 'last_frame': None, 'reference_images': []
        }):
            result = self.driver.build_create_request(ai_tool)
            self.assertFalse(result['success'])
            self.assertIn('首帧图片', result['error'])

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_last_frame_compress_failure_skipped(self, mock_compress):
        """尾帧压缩失败：跳过尾帧，仅保留首帧（不带 role）"""
        def side_effect(url, config, max_size_mb=10.0, is_local=True):
            if 'first' in url:
                return (True, 'https://cdn.example.com/first.jpg', None)
            return (False, None, '压缩失败')

        mock_compress.side_effect = side_effect
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg,http://example.com/last.jpg',
            extra_config={'image_mode': 'first_last_frame'}
        )

        result = self.driver.build_create_request(ai_tool)
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        # 尾帧失败，只有首帧，不带 role
        self.assertEqual(len(image_items), 1)
        self.assertNotIn('role', image_items[0])

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_prompt_included_in_content(self, mock_compress):
        """提示词出现在 content 数组中"""
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(
            prompt='一只猫在跳舞',
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_frame'}
        )

        result = self.driver.build_create_request(ai_tool)
        text_items = [c for c in result['json']['content'] if c['type'] == 'text']
        self.assertEqual(len(text_items), 1)
        self.assertEqual(text_items[0]['text'], '一只猫在跳舞')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_first_last_with_ref_degrades_to_first_last(self, mock_compress):
        """first_last_with_ref 模式降级为首尾帧处理"""
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_with_ref'}
        )

        result = self.driver.build_create_request(ai_tool)
        # 应该走首尾帧分支，成功构建
        self.assertIn('json', result)
        self.assertIn('model', result['json'])


class TestBuildCreateRequestTextToVideo(unittest.TestCase):
    """测试文生视频模式下的 build_create_request"""

    def setUp(self):
        self.driver = _create_driver()

    def test_text_to_video_content_only_text(self):
        """文生视频：无任何媒体输入、extra_config 为空，content 仅一个 text 元素"""
        ai_tool = _make_ai_tool(
            prompt='一只猫在跳舞',
            image_path=None,
            extra_config=None,
            ratio='9:16',
            duration=5
        )

        result = self.driver.build_create_request(ai_tool)

        # content 仅含 text
        content = result['json']['content']
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]['type'], 'text')
        self.assertEqual(content[0]['text'], '一只猫在跳舞')
        # payload 含 model / ratio / duration
        self.assertEqual(result['json']['model'], 'doubao-seedance-1-5-pro-251215')
        self.assertEqual(result['json']['ratio'], '9:16')
        self.assertEqual(result['json']['duration'], 5)
        # url / method / headers 正确
        self.assertIn('/api/v3/contents/generations/tasks', result['url'])
        self.assertEqual(result['method'], 'POST')
        self.assertIn('Authorization', result['headers'])

    def test_text_to_video_empty_prompt_returns_error(self):
        """文生视频但 prompt 为空：返回 USER 错误"""
        ai_tool = _make_ai_tool(
            prompt='',
            image_path=None,
            extra_config=None
        )

        result = self.driver.build_create_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertIn('提示词', result['error'])

    def test_text_to_video_whitespace_prompt_returns_error(self):
        """文生视频但 prompt 仅为空白字符：返回 USER 错误"""
        ai_tool = _make_ai_tool(
            prompt='   ',
            image_path=None,
            extra_config=None
        )

        result = self.driver.build_create_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')

    def test_image_mode_declared_no_media_not_text_to_video(self):
        """边界守护 A：图生视频接口任务（extra_config 带 image_mode）即使无任何媒体输入，
        也不被判为文生视频（走首尾帧逻辑并按原逻辑报错）"""
        ai_tool = _make_ai_tool(
            prompt='测试',
            image_path=None,
            extra_config={'image_mode': 'first_last_frame'}
        )

        result = self.driver.build_create_request(ai_tool)

        # 走首尾帧分支：因无首帧报错，而非被判为文生视频而成功
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertIn('首帧图片', result['error'])

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_multi_reference_with_only_video_not_text_to_video(self, mock_compress, mock_upload_cdn):
        """边界守护 B：multi_reference + 仅参考视频、无图片，不被判为文生视频，
        走多参考图逻辑并构建含 reference_video 的 content"""
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/video.mp4', None)
        ai_tool = _make_ai_tool(
            prompt='参考视频生成',
            image_path=None,
            extra_config={'image_mode': 'multi_reference', 'reference_video': 'http://example.com/video.mp4'},
            reference_images=None,
            video_path=None
        )

        result = self.driver.build_create_request(ai_tool)

        # 走 multi_reference 分支：content 含 reference_video，而非被判为文生视频（仅 text）
        video_items = [c for c in result['json']['content'] if c['type'] == 'video_url']
        self.assertEqual(len(video_items), 1)
        self.assertEqual(video_items[0].get('role'), 'reference_video')


class TestBuildCreateRequestMultiReference(unittest.TestCase):
    """测试多参考图模式下的 build_create_request"""

    def setUp(self):
        self.driver = _create_driver()

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_multi_reference_images_with_roles(self, mock_compress, mock_upload_cdn):
        """多参考图模式：图片带 role=reference_image"""
        mock_compress.return_value = (True, 'https://cdn.example.com/ref.jpg', None)
        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'image_mode': 'multi_reference'},
            reference_images=json.dumps(['http://example.com/ref1.jpg', 'http://example.com/ref2.jpg'])
        )

        result = self.driver.build_create_request(ai_tool)

        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(len(image_items), 2)
        for item in image_items:
            self.assertEqual(item.get('role'), 'reference_image')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_reference_video_uploaded_to_cdn(self, mock_compress, mock_upload_cdn):
        """参考视频通过 upload_media_to_cdn_sync 上传到 CDN"""
        mock_compress.return_value = (True, 'https://cdn.example.com/ref.jpg', None)
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/video.mp4', None)
        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'image_mode': 'multi_reference', 'reference_video': 'http://example.com/video.mp4'},
            reference_images=json.dumps(['http://example.com/ref1.jpg']),
            video_path=None
        )

        result = self.driver.build_create_request(ai_tool)

        video_items = [c for c in result['json']['content'] if c['type'] == 'video_url']
        self.assertEqual(len(video_items), 1)
        self.assertEqual(video_items[0].get('role'), 'reference_video')
        self.assertEqual(video_items[0]['video_url']['url'], 'https://cdn.example.com/video.mp4')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_reference_audio_uploaded_to_cdn(self, mock_compress, mock_upload_cdn):
        """参考音频通过 upload_media_to_cdn_sync 上传到 CDN"""
        mock_compress.return_value = (True, 'https://cdn.example.com/ref.jpg', None)
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/audio.mp3', None)
        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'image_mode': 'multi_reference', 'reference_audio': 'http://example.com/audio.mp3'},
            reference_images=json.dumps(['http://example.com/ref1.jpg']),
            audio_path=None
        )

        result = self.driver.build_create_request(ai_tool)

        audio_items = [c for c in result['json']['content'] if c['type'] == 'audio_url']
        self.assertEqual(len(audio_items), 1)
        self.assertEqual(audio_items[0].get('role'), 'reference_audio')
        self.assertEqual(audio_items[0]['audio_url']['url'], 'https://cdn.example.com/audio.mp3')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_video_from_ai_tool_attribute(self, mock_compress, mock_upload_cdn):
        """参考视频优先从 ai_tool.video_path 获取"""
        mock_compress.return_value = (True, 'https://cdn.example.com/ref.jpg', None)
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/video.mp4', None)
        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'image_mode': 'multi_reference'},
            reference_images=json.dumps(['http://example.com/ref1.jpg']),
            video_path='http://example.com/ai_tool_video.mp4'
        )

        result = self.driver.build_create_request(ai_tool)

        # 验证 upload_media_to_cdn_sync 被调用时传入的是 ai_tool.video_path
        video_calls = [c for c in mock_upload_cdn.call_args_list if 'video' in str(c).lower() or 'ai_tool_video' in str(c)]
        self.assertTrue(any('ai_tool_video' in str(c) for c in mock_upload_cdn.call_args_list))

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_audio_from_ai_tool_attribute(self, mock_compress, mock_upload_cdn):
        """参考音频优先从 ai_tool.audio_path 获取"""
        mock_compress.return_value = (True, 'https://cdn.example.com/ref.jpg', None)
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/audio.mp3', None)
        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'image_mode': 'multi_reference'},
            reference_images=json.dumps(['http://example.com/ref1.jpg']),
            audio_path='http://example.com/ai_tool_audio.mp3'
        )

        result = self.driver.build_create_request(ai_tool)
        self.assertTrue(any('ai_tool_audio' in str(c) for c in mock_upload_cdn.call_args_list))

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_video_upload_failure_skipped(self, mock_compress, mock_upload_cdn):
        """参考视频上传 CDN 失败：跳过，不阻断流程"""
        mock_compress.return_value = (True, 'https://cdn.example.com/ref.jpg', None)
        mock_upload_cdn.return_value = (False, None, '上传失败')
        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'image_mode': 'multi_reference', 'reference_video': 'http://example.com/video.mp4'},
            reference_images=json.dumps(['http://example.com/ref1.jpg']),
            video_path=None
        )

        result = self.driver.build_create_request(ai_tool)
        # 不应包含视频，但请求应成功构建
        video_items = [c for c in result['json']['content'] if c['type'] == 'video_url']
        self.assertEqual(len(video_items), 0)

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_audio_upload_failure_skipped(self, mock_compress, mock_upload_cdn):
        """参考音频上传 CDN 失败：跳过，不阻断流程"""
        mock_compress.return_value = (True, 'https://cdn.example.com/ref.jpg', None)
        mock_upload_cdn.return_value = (False, None, '上传失败')
        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'image_mode': 'multi_reference', 'reference_audio': 'http://example.com/audio.mp3'},
            reference_images=json.dumps(['http://example.com/ref1.jpg']),
            audio_path=None
        )

        result = self.driver.build_create_request(ai_tool)
        audio_items = [c for c in result['json']['content'] if c['type'] == 'audio_url']
        self.assertEqual(len(audio_items), 0)

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_no_reference_images_builds_request(self, mock_compress):
        """多参考图模式但没有参考图：仍然构建请求（图片可选，视频/音频可独立使用）"""
        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'image_mode': 'multi_reference'},
            reference_images=None
        )
        with patch.object(self.driver, 'get_all_images_by_mode', return_value={
            'mode': 'multi_reference', 'first_frame': None, 'last_frame': None, 'reference_images': []
        }):
            result = self.driver.build_create_request(ai_tool)
            self.assertIn('url', result)
            self.assertIn('method', result)
            self.assertIn('json', result)

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_all_reference_images_compress_failure_builds_request(self, mock_compress):
        """所有参考图压缩失败：仍然构建请求（跳过失败的图片）"""
        mock_compress.return_value = (False, None, '压缩失败')
        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'image_mode': 'multi_reference'},
            reference_images=json.dumps(['http://example.com/ref1.jpg'])
        )

        result = self.driver.build_create_request(ai_tool)
        self.assertIn('url', result)
        self.assertIn('method', result)
        self.assertIn('json', result)
        # content 中不应有 image_url（所有图片压缩失败被跳过）
        image_items = [c for c in result['json']['content'] if c.get('type') == 'image_url']
        self.assertEqual(len(image_items), 0)


class TestBuildCreateRequestFallback(unittest.TestCase):
    """测试降级模式（未知 image_mode）"""

    def setUp(self):
        self.driver = _create_driver()

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_unknown_mode_fallback_to_first_last(self, mock_compress):
        """未知模式降级为首尾帧处理"""
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'unknown_mode'}
        )
        with patch.object(self.driver, 'get_all_images_by_mode', return_value={
            'mode': 'unknown_mode', 'first_frame': 'http://example.com/first.jpg',
            'last_frame': None, 'reference_images': []
        }):
            result = self.driver.build_create_request(ai_tool)
            self.assertIn('json', result)
            self.assertIn('model', result['json'])

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_unknown_mode_no_first_frame(self, mock_compress):
        """未知模式且无首帧：返回错误"""
        ai_tool = _make_ai_tool(image_path=None, extra_config={'image_mode': 'unknown_mode'})
        with patch.object(self.driver, 'get_all_images_by_mode', return_value={
            'mode': 'unknown_mode', 'first_frame': None,
            'last_frame': None, 'reference_images': []
        }):
            result = self.driver.build_create_request(ai_tool)
            self.assertFalse(result['success'])
            self.assertIn('未找到可用的图片', result['error'])


class TestBuildCreateRequestPayload(unittest.TestCase):
    """测试 payload 构建的通用部分"""

    def setUp(self):
        self.driver = _create_driver()

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_optional_generate_audio(self, mock_compress):
        """可选参数 generate_audio"""
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_frame', 'generate_audio': True}
        )

        result = self.driver.build_create_request(ai_tool)
        self.assertTrue(result['json'].get('generate_audio'))

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_optional_watermark(self, mock_compress):
        """可选参数 watermark"""
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_frame', 'watermark': False}
        )

        result = self.driver.build_create_request(ai_tool)
        self.assertFalse(result['json'].get('watermark'))

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_ratio_from_ai_tool(self, mock_compress):
        """ratio 从 ai_tool.ratio 获取（如 9:16）"""
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_frame'},
            ratio='9:16'
        )

        result = self.driver.build_create_request(ai_tool)
        self.assertEqual(result['json'].get('ratio'), '9:16')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_ratio_not_set(self, mock_compress):
        """ai_tool 未设置 ratio 时，payload 中不包含 ratio"""
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_frame'}
        )

        result = self.driver.build_create_request(ai_tool)
        self.assertNotIn('ratio', result['json'])

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_duration_from_ai_tool(self, mock_compress):
        """duration 从 ai_tool 获取"""
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_frame'},
            duration=10
        )

        result = self.driver.build_create_request(ai_tool)
        self.assertEqual(result['json'].get('duration'), 10)

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_request_headers_and_url(self, mock_compress):
        """验证请求的 headers 和 URL"""
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_frame'}
        )

        result = self.driver.build_create_request(ai_tool)
        self.assertEqual(result['method'], 'POST')
        self.assertIn('/api/v3/contents/generations/tasks', result['url'])
        self.assertIn('Bearer', result['headers']['Authorization'])
        self.assertEqual(result['headers']['Content-Type'], 'application/json')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_no_optional_params_when_not_set(self, mock_compress):
        """未设置的可选参数不出现在 payload 中"""
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_frame'},
            duration=None
        )

        result = self.driver.build_create_request(ai_tool)
        self.assertNotIn('generate_audio', result['json'])
        self.assertNotIn('watermark', result['json'])
        self.assertNotIn('ratio', result['json'])
        self.assertNotIn('duration', result['json'])


class TestSubmitTaskTestMode(unittest.TestCase):
    """测试 submit_task 的测试模式"""

    def test_test_mode_returns_mock_project_id(self):
        """测试模式返回 mock project_id，不发起真实 API 请求"""
        driver = _create_driver(test_mode=True)
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'image_mode': 'first_last_frame'}
        )
        with patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync',
                   return_value=(True, 'https://cdn.example.com/first.jpg', None)):
            result = driver.submit_task(ai_tool)

        self.assertTrue(result['success'])
        self.assertIn('project_id', result)
        self.assertTrue(result['project_id'].startswith('test-'))


class TestCheckStatusTestMode(unittest.TestCase):
    """测试 check_status 的测试模式"""

    def test_test_mode_returns_mock_video(self):
        """测试模式返回 mock 视频结果，不发起真实 API 请求"""
        driver = _create_driver(test_mode=True, mock_video_url='https://cdn.example.com/mock.mp4')
        result = driver.check_status('cgt-xxx')

        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://cdn.example.com/mock.mp4')

    def test_test_mode_without_mock_url_skips(self):
        """测试模式但没有配置 mock_video_url：跳过 mock，走正常流程"""
        driver = _create_driver(test_mode=True, mock_video_url=None)
        # 没有配置 mock URL，测试模式不会拦截，会走正常流程（会报错因为没有真实 API）
        # 这里只验证不会进入测试模式分支
        with patch.object(driver, '_request', return_value={"id": "cgt-xxx", "status": "running"}):
            result = driver.check_status('cgt-xxx')
            self.assertEqual(result['status'], 'RUNNING')


class TestCheckStatusMapping(unittest.TestCase):
    """测试 check_status 的状态映射"""

    def setUp(self):
        self.driver = _create_driver(test_mode=False)

    def test_succeeded_maps_to_SUCCESS(self):
        """succeeded -> SUCCESS"""
        with patch.object(self.driver, '_request', return_value={
            "id": "cgt-xxx", "status": "succeeded",
            "content": {"video_url": "https://cdn.example.com/result.mp4"}
        }):
            result = self.driver.check_status('cgt-xxx')
            self.assertEqual(result['status'], 'SUCCESS')
            self.assertEqual(result['result_url'], 'https://cdn.example.com/result.mp4')

    def test_failed_maps_to_FAILED(self):
        """failed -> FAILED"""
        with patch.object(self.driver, '_request', return_value={
            "id": "cgt-xxx", "status": "failed",
            "error": {"message": "内容审核不通过"}
        }):
            result = self.driver.check_status('cgt-xxx')
            self.assertEqual(result['status'], 'FAILED')
            self.assertIn('审核', result['error'])

    def test_running_maps_to_RUNNING(self):
        """running -> RUNNING"""
        with patch.object(self.driver, '_request', return_value={
            "id": "cgt-xxx", "status": "running"
        }):
            result = self.driver.check_status('cgt-xxx')
            self.assertEqual(result['status'], 'RUNNING')

    def test_queued_maps_to_RUNNING(self):
        """queued -> RUNNING（中间状态统一映射为 RUNNING）"""
        with patch.object(self.driver, '_request', return_value={
            "id": "cgt-xxx", "status": "queued"
        }):
            result = self.driver.check_status('cgt-xxx')
            self.assertEqual(result['status'], 'RUNNING')

    def test_network_error_returns_RUNNING(self):
        """网络异常返回 RUNNING（允许后续重试）"""
        with patch.object(self.driver, '_request', side_effect=ConnectionError("连接超时")):
            result = self.driver.check_status('cgt-xxx')
            self.assertEqual(result['status'], 'RUNNING')


class TestSubmitTaskNetworkError(unittest.TestCase):
    """测试 submit_task 的网络错误处理"""

    def setUp(self):
        self.driver = _create_driver(test_mode=False)

    def test_connection_error_returns_retry(self):
        """连接错误返回 retry=True"""
        with patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync',
                   return_value=(True, 'https://cdn.example.com/first.jpg', None)):
            with patch.object(self.driver, '_request', side_effect=ConnectionError("连接超时")):
                ai_tool = _make_ai_tool(
                    image_path='http://example.com/first.jpg',
                    extra_config={'image_mode': 'first_last_frame'}
                )
                result = self.driver.submit_task(ai_tool)
                self.assertFalse(result['success'])
                self.assertTrue(result['retry'])

    def test_timeout_error_returns_retry(self):
        """超时错误返回 retry=True"""
        with patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync',
                   return_value=(True, 'https://cdn.example.com/first.jpg', None)):
            with patch.object(self.driver, '_request', side_effect=TimeoutError("请求超时")):
                ai_tool = _make_ai_tool(
                    image_path='http://example.com/first.jpg',
                    extra_config={'image_mode': 'first_last_frame'}
                )
                result = self.driver.submit_task(ai_tool)
                self.assertFalse(result['success'])
                self.assertTrue(result['retry'])


class TestSubclassDrivers(unittest.TestCase):
    """测试子类实例化"""

    def test_seedance_15_pro_driver(self):
        """Seedance 1.5 Pro 子类"""
        from task.visual_drivers.seedance_volcengine_v1_driver import Seedance15ProVolcengineV1Driver
        with patch('task.visual_drivers.seedance_volcengine_v1_driver.get_dynamic_config_value') as mock_config, \
             patch('task.visual_drivers.seedance_volcengine_v1_driver.get_config', return_value={}):

            def side_effect(*keys, default=None):
                key_map = {
                    ('volcengine', 'api_key'): 'test_key',
                    ('timeout', 'request_timeout'): 30,
                    ('server', 'is_local'): False,
                    ('test_mode', 'enabled'): False,
                    ('test_mode', 'mock_videos'): {},
                }
                return key_map.get(keys, default)

            mock_config.side_effect = side_effect
            driver = Seedance15ProVolcengineV1Driver()
            self.assertEqual(driver.driver_name, 'seedance_1_5_pro_volcengine_v1')
            self.assertEqual(driver.driver_type, 21)
            self.assertEqual(driver._model, 'doubao-seedance-1-5-pro-251215')

    def test_seedance_20_fast_driver(self):
        """Seedance 2.0 Fast 子类"""
        from task.visual_drivers.seedance_volcengine_v1_driver import Seedance20FastVolcengineV1Driver
        with patch('task.visual_drivers.seedance_volcengine_v1_driver.get_dynamic_config_value') as mock_config, \
             patch('task.visual_drivers.seedance_volcengine_v1_driver.get_config', return_value={}):

            def side_effect(*keys, default=None):
                key_map = {
                    ('volcengine', 'api_key'): 'test_key',
                    ('timeout', 'request_timeout'): 30,
                    ('server', 'is_local'): False,
                    ('test_mode', 'enabled'): False,
                    ('test_mode', 'mock_videos'): {},
                }
                return key_map.get(keys, default)

            mock_config.side_effect = side_effect
            driver = Seedance20FastVolcengineV1Driver()
            self.assertEqual(driver.driver_name, 'seedance_2_0_fast_volcengine_v1')
            self.assertEqual(driver.driver_type, 22)
            self.assertEqual(driver._model, 'doubao-seedance-2-0-fast-260128')

    def test_seedance_20_driver(self):
        """Seedance 2.0 子类"""
        from task.visual_drivers.seedance_volcengine_v1_driver import Seedance20VolcengineV1Driver
        with patch('task.visual_drivers.seedance_volcengine_v1_driver.get_dynamic_config_value') as mock_config, \
             patch('task.visual_drivers.seedance_volcengine_v1_driver.get_config', return_value={}):

            def side_effect(*keys, default=None):
                key_map = {
                    ('volcengine', 'api_key'): 'test_key',
                    ('timeout', 'request_timeout'): 30,
                    ('server', 'is_local'): False,
                    ('test_mode', 'enabled'): False,
                    ('test_mode', 'mock_videos'): {},
                }
                return key_map.get(keys, default)

            mock_config.side_effect = side_effect
            driver = Seedance20VolcengineV1Driver()
            self.assertEqual(driver.driver_name, 'seedance_2_0_volcengine_v1')
            self.assertEqual(driver.driver_type, 23)
            self.assertEqual(driver._model, 'doubao-seedance-2-0-260128')


class TestParseExtraConfig(unittest.TestCase):
    """测试 _parse_extra_config 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_dict_extra_config(self):
        """extra_config 为字典类型"""
        ai_tool = _make_ai_tool(extra_config={'image_mode': 'first_last_frame', 'ratio': '16:9'})
        result = self.driver._parse_extra_config(ai_tool)
        self.assertEqual(result['image_mode'], 'first_last_frame')
        self.assertEqual(result['ratio'], '16:9')

    def test_json_string_extra_config(self):
        """extra_config 为 JSON 字符串"""
        ai_tool = _make_ai_tool(extra_config=json.dumps({'image_mode': 'multi_reference'}))
        result = self.driver._parse_extra_config(ai_tool)
        self.assertEqual(result['image_mode'], 'multi_reference')

    def test_none_extra_config(self):
        """extra_config 为 None"""
        ai_tool = _make_ai_tool(extra_config=None)
        result = self.driver._parse_extra_config(ai_tool)
        self.assertEqual(result, {})

    def test_invalid_json_extra_config(self):
        """extra_config 为无效 JSON 字符串"""
        ai_tool = _make_ai_tool(extra_config='not a json')
        result = self.driver._parse_extra_config(ai_tool)
        self.assertEqual(result, {})


class TestResolveImagePathWithFaceMask(unittest.TestCase):
    """测试 _resolve_image_path_with_face_mask（图片遮盖替换，对齐视频）"""

    def setUp(self):
        self.driver = _create_driver()
        self.ai_tool = _make_ai_tool()

    def _make_step(self, step_type='image_face_mask', status=PipelineStepStatus.COMPLETED,
                   target='http://example.com/ref1.jpg', result_url='/upload/cache/masked.png'):
        step = MagicMock()
        step.step_type = step_type
        step.status = status
        step.target = target
        step.result_url = result_url
        return step

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.PipelineStepModel')
    def test_completed_matching_step_returns_result_url(self, MockStepModel):
        """COMPLETED 且 target 匹配的 image_face_mask 步骤：返回遮盖路径"""
        MockStepModel.get_by_ai_tool_and_stage.return_value = [self._make_step()]
        result = self.driver._resolve_image_path_with_face_mask(self.ai_tool, 'http://example.com/ref1.jpg')
        self.assertEqual(result, '/upload/cache/masked.png')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.PipelineStepModel')
    def test_target_mismatch_returns_original(self, MockStepModel):
        """target 不匹配：返回原始路径"""
        MockStepModel.get_by_ai_tool_and_stage.return_value = [self._make_step(target='http://other.com/x.jpg')]
        result = self.driver._resolve_image_path_with_face_mask(self.ai_tool, 'http://example.com/ref1.jpg')
        self.assertEqual(result, 'http://example.com/ref1.jpg')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.PipelineStepModel')
    def test_non_completed_step_skipped(self, MockStepModel):
        """非 COMPLETED 的步骤被跳过：返回原始路径"""
        MockStepModel.get_by_ai_tool_and_stage.return_value = [self._make_step(status=PipelineStepStatus.PROCESSING)]
        result = self.driver._resolve_image_path_with_face_mask(self.ai_tool, 'http://example.com/ref1.jpg')
        self.assertEqual(result, 'http://example.com/ref1.jpg')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.PipelineStepModel')
    def test_face_mask_step_type_ignored(self, MockStepModel):
        """FACE_MASK（视频）步骤不参与图片替换：返回原始路径"""
        MockStepModel.get_by_ai_tool_and_stage.return_value = [self._make_step(step_type='face_mask')]
        result = self.driver._resolve_image_path_with_face_mask(self.ai_tool, 'http://example.com/ref1.jpg')
        self.assertEqual(result, 'http://example.com/ref1.jpg')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.PipelineStepModel')
    def test_no_steps_returns_original(self, MockStepModel):
        """无任何步骤：返回原始路径"""
        MockStepModel.get_by_ai_tool_and_stage.return_value = []
        result = self.driver._resolve_image_path_with_face_mask(self.ai_tool, 'http://example.com/ref1.jpg')
        self.assertEqual(result, 'http://example.com/ref1.jpg')

    def test_empty_image_path_returns_empty(self):
        """空图片路径：直接返回空，不查询 step"""
        with patch('task.visual_drivers.seedance_volcengine_v1_driver.PipelineStepModel') as MockStepModel:
            result = self.driver._resolve_image_path_with_face_mask(self.ai_tool, '')
            self.assertEqual(result, '')
            MockStepModel.get_by_ai_tool_and_stage.assert_not_called()

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.PipelineStepModel')
    def test_exception_returns_original(self, MockStepModel):
        """查询异常：返回原始路径，不抛出"""
        MockStepModel.get_by_ai_tool_and_stage.side_effect = RuntimeError('db error')
        result = self.driver._resolve_image_path_with_face_mask(self.ai_tool, 'http://example.com/ref1.jpg')
        self.assertEqual(result, 'http://example.com/ref1.jpg')


class TestBuildCreateRequestUsesFaceMaskedImage(unittest.TestCase):
    """端到端验证 build_create_request 实际使用遮盖后的图片"""

    def setUp(self):
        self.driver = _create_driver()

    def _make_image_face_mask_step(self, target, result_url):
        step = MagicMock()
        step.step_type = 'image_face_mask'
        step.status = PipelineStepStatus.COMPLETED
        step.target = target
        step.result_url = result_url
        return step

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.PipelineStepModel')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_multi_reference_uses_masked_image(self, mock_compress, MockStepModel):
        """多参考图模式：compress 收到的是遮盖路径而非原始 URL"""
        original_url = 'http://example.com/ref1.jpg'
        masked_path = '/upload/cache/2026-06-26/masked.png'
        MockStepModel.get_by_ai_tool_and_stage.return_value = [
            self._make_image_face_mask_step(original_url, masked_path)
        ]
        mock_compress.return_value = (True, 'https://cdn.example.com/masked.png', None)

        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'image_mode': 'multi_reference'},
            reference_images=json.dumps([original_url])
        )
        self.driver.build_create_request(ai_tool)

        self.assertGreater(mock_compress.call_count, 0)
        self.assertEqual(mock_compress.call_args_list[0].args[0], masked_path)

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.PipelineStepModel')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_first_last_frame_uses_masked_image(self, mock_compress, MockStepModel):
        """首尾帧模式：首帧 compress 收到的是遮盖路径"""
        original_url = 'http://example.com/first.jpg'
        masked_path = '/upload/cache/2026-06-26/masked_first.png'
        MockStepModel.get_by_ai_tool_and_stage.return_value = [
            self._make_image_face_mask_step(original_url, masked_path)
        ]
        mock_compress.return_value = (True, 'https://cdn.example.com/masked_first.png', None)

        ai_tool = _make_ai_tool(
            image_path=original_url,
            extra_config={'image_mode': 'first_last_frame'}
        )
        self.driver.build_create_request(ai_tool)

        self.assertGreater(mock_compress.call_count, 0)
        self.assertEqual(mock_compress.call_args_list[0].args[0], masked_path)


if __name__ == '__main__':
    unittest.main()
