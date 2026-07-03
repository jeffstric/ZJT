"""
Happy Horse 阿里云百炼驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

测试覆盖：
- 三种驱动模式初始化（i2v/r2v/t2v）
- 响应格式验证（submit_response / status_response）
- i2v 请求构建（首帧 + 可选音频/视频）
- r2v 请求构建（多参考图，兼容 image_path 和 reference_images）
- t2v 请求构建（仅提示词）
- extra_config 参数解析
- 音频校验
- r2v 图片 URL 获取（两种存储方式）
- submit_task 流程（成功/校验失败/网络异常/API错误）
- check_status 状态映射
- 子类实例化
"""
import json
import sys
import unittest
from unittest.mock import patch, MagicMock

# Mock 外部依赖（必须在 import driver 之前）
sys.modules['utils.sentry_util'] = MagicMock()
sys.modules['utils.image_upload_utils'] = MagicMock()
sys.modules['api.media'] = MagicMock()


def _create_driver(driver_type=28, driver_name="happy_horse_dashscope_v1", api_key='test_api_key'):
    """创建 HappyHorseDashscopeV1Driver 实例（mock 所有外部依赖）"""
    from task.visual_drivers.happy_horse_dashscope_v1_driver import HappyHorseDashscopeV1Driver

    with patch('task.visual_drivers.happy_horse_dashscope_v1_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.happy_horse_dashscope_v1_driver.get_config', return_value={}):

        def side_effect(*keys, default=None):
            key_map = {
                ('llm', 'qwen', 'api_key'): api_key,
                ('timeout', 'request_timeout'): 30,
                ('server', 'is_local'): False,
            }
            return key_map.get(keys, default)

        mock_config.side_effect = side_effect
        driver = HappyHorseDashscopeV1Driver(driver_name=driver_name, driver_type=driver_type)
        return driver


def _make_ai_tool(prompt='测试提示词', image_path='http://example.com/first.jpg',
                  extra_config=None, duration=5, ratio='16:9',
                  reference_images=None, audio_path=None, video_path=None):
    """创建模拟的 ai_tool 对象"""
    tool = MagicMock()
    tool.id = 2001
    tool.prompt = prompt
    tool.image_path = image_path
    tool.extra_config = extra_config
    tool.duration = duration
    tool.ratio = ratio
    tool.reference_images = reference_images
    tool.audio_path = audio_path
    tool.video_path = video_path
    return tool


# ============================================================
# 驱动初始化测试
# ============================================================
class TestHappyHorseDriverInit(unittest.TestCase):
    """测试驱动初始化"""

    def test_i2v_default_init(self):
        """i2v 模式默认初始化"""
        driver = _create_driver(driver_type=28)
        self.assertEqual(driver.driver_type, 28)
        self.assertEqual(driver._api_key, 'test_api_key')
        self.assertEqual(driver._base_url, 'https://dashscope.aliyuncs.com/api/v1')
        self.assertEqual(driver.MODEL, 'happyhorse-1.0-i2v')

    def test_r2v_driver_type(self):
        """r2v 模式 driver_type=29"""
        driver = _create_driver(driver_type=29, driver_name='happy_horse_dashscope_r2v_v1')
        self.assertEqual(driver.driver_type, 29)

    def test_t2v_driver_type(self):
        """t2v 模式 driver_type=30"""
        driver = _create_driver(driver_type=30, driver_name='happy_horse_dashscope_t2v_v1')
        self.assertEqual(driver.driver_type, 30)

    def test_missing_api_key_raises(self):
        """API Key 为空时抛出异常"""
        from task.visual_drivers.happy_horse_dashscope_v1_driver import HappyHorseDashscopeV1Driver
        from task.visual_drivers.base_video_driver import DriverConfigError

        with patch('task.visual_drivers.happy_horse_dashscope_v1_driver.get_dynamic_config_value',
                   return_value=''), \
             patch('task.visual_drivers.happy_horse_dashscope_v1_driver.get_config', return_value={}):
            with self.assertRaises(DriverConfigError):
                HappyHorseDashscopeV1Driver()


# ============================================================
# 响应验证测试
# ============================================================
class TestValidateSubmitResponse(unittest.TestCase):
    """测试 _validate_submit_response 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_valid_response(self):
        """正确格式的 submit 响应"""
        result = {"output": {"task_status": "PENDING", "task_id": "abc-123"}}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_response_with_error_field(self):
        """包含 error 字段的响应视为格式有效"""
        result = {"error": {"message": "rate limit"}}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertTrue(is_valid)

    def test_missing_output(self):
        """缺少 output 字段"""
        result = {"request_id": "xxx"}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertFalse(is_valid)
        self.assertIn("output", error)

    def test_missing_task_id(self):
        """output 中缺少 task_id"""
        result = {"output": {"task_status": "PENDING"}}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertFalse(is_valid)
        self.assertIn("task_id", error)

    def test_non_dict_response(self):
        """非字典响应"""
        is_valid, error = self.driver._validate_submit_response("invalid")
        self.assertFalse(is_valid)
        self.assertIn("字典", error)


class TestValidateStatusResponse(unittest.TestCase):
    """测试 _validate_status_response 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_valid_succeeded(self):
        """成功状态响应"""
        result = {"output": {"task_id": "xxx", "task_status": "SUCCEEDED"}}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertTrue(is_valid)

    def test_valid_running(self):
        """运行中状态响应"""
        result = {"output": {"task_id": "xxx", "task_status": "RUNNING"}}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertTrue(is_valid)

    def test_response_with_error_field(self):
        """包含 error 字段视为有效"""
        result = {"error": {"message": "fail"}}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertTrue(is_valid)

    def test_missing_task_status(self):
        """缺少 task_status 字段"""
        result = {"output": {"task_id": "xxx"}}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertFalse(is_valid)
        self.assertIn("task_status", error)

    def test_missing_output(self):
        """缺少 output 字段"""
        result = {"request_id": "xxx"}
        is_valid, error = self.driver._validate_status_response(result)
        self.assertFalse(is_valid)
        self.assertIn("output", error)


# ============================================================
# extra_config 参数解析测试
# ============================================================
class TestParseExtraParams(unittest.TestCase):
    """测试 _parse_extra_params 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_default_values(self):
        """无 extra_config 时使用默认值"""
        ai_tool = _make_ai_tool(extra_config=None)
        result = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(result['resolution'], '720P')
        self.assertFalse(result['watermark'])
        self.assertTrue(result['prompt_extend'])

    def test_json_string_config(self):
        """JSON 字符串格式 extra_config"""
        ai_tool = _make_ai_tool(extra_config=json.dumps({
            'resolution': '720P',
            'watermark': True,
            'seed': 42,
            'prompt_extend': False
        }))
        result = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(result['resolution'], '720P')
        self.assertTrue(result['watermark'])
        self.assertEqual(result['seed'], 42)
        self.assertFalse(result['prompt_extend'])

    def test_dict_config(self):
        """字典格式 extra_config"""
        ai_tool = _make_ai_tool(extra_config={
            'resolution': '720P',
            'watermark': False
        })
        result = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(result['resolution'], '720P')
        self.assertFalse(result['watermark'])

    def test_video_resolution_preferred_over_legacy_resolution(self):
        """优先使用 video_resolution，兼容旧 resolution 字段"""
        ai_tool = _make_ai_tool(extra_config={
            'resolution': '720P',
            'video_resolution': '1080P',
        })
        result = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(result['resolution'], '1080P')

    def test_invalid_resolution_ignored(self):
        """无效的 resolution 值被忽略，使用默认值"""
        ai_tool = _make_ai_tool(extra_config={'resolution': '4K'})
        result = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(result['resolution'], '720P')

    def test_seed_out_of_range_ignored(self):
        """超出范围的 seed 被忽略"""
        ai_tool = _make_ai_tool(extra_config={'seed': 9999999999})
        result = self.driver._parse_extra_params(ai_tool)
        self.assertNotIn('seed', result)

    def test_invalid_json_string(self):
        """无效 JSON 字符串使用默认值"""
        ai_tool = _make_ai_tool(extra_config='not json')
        result = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(result['resolution'], '720P')


# ============================================================
# r2v 图片 URL 获取测试
# ============================================================
class TestGetR2vImageUrls(unittest.TestCase):
    """测试 _get_r2v_image_urls 方法"""

    def setUp(self):
        self.driver = _create_driver(driver_type=29)

    def test_from_image_path_comma_separated(self):
        """从 image_path 逗号分隔读取"""
        ai_tool = _make_ai_tool(image_path='http://a.jpg,http://b.jpg,http://c.jpg')
        result = self.driver._get_r2v_image_urls(ai_tool)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], 'http://a.jpg')

    def test_from_reference_images_json(self):
        """从 reference_images JSON 数组读取"""
        ai_tool = _make_ai_tool(
            image_path=None,
            reference_images=json.dumps(['http://x.jpg', 'http://y.jpg'])
        )
        result = self.driver._get_r2v_image_urls(ai_tool)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], 'http://x.jpg')

    def test_image_path_takes_priority(self):
        """image_path 优先于 reference_images"""
        ai_tool = _make_ai_tool(
            image_path='http://path.jpg',
            reference_images=json.dumps(['http://ref.jpg'])
        )
        result = self.driver._get_r2v_image_urls(ai_tool)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], 'http://path.jpg')

    def test_empty_image_path_falls_back_to_reference(self):
        """image_path 为空时回退到 reference_images"""
        ai_tool = _make_ai_tool(
            image_path='',
            reference_images=json.dumps(['http://ref.jpg'])
        )
        result = self.driver._get_r2v_image_urls(ai_tool)
        self.assertEqual(len(result), 1)

    def test_both_empty_returns_empty(self):
        """两者都为空返回空列表"""
        ai_tool = _make_ai_tool(image_path=None, reference_images=None)
        result = self.driver._get_r2v_image_urls(ai_tool)
        self.assertEqual(result, [])

    def test_invalid_reference_images_json(self):
        """无效 JSON 的 reference_images 返回空列表"""
        ai_tool = _make_ai_tool(image_path=None, reference_images='not json')
        result = self.driver._get_r2v_image_urls(ai_tool)
        self.assertEqual(result, [])

    def test_whitespace_stripped(self):
        """URL 前后空格被清除"""
        ai_tool = _make_ai_tool(image_path=' http://a.jpg , http://b.jpg ')
        result = self.driver._get_r2v_image_urls(ai_tool)
        self.assertEqual(result[0], 'http://a.jpg')
        self.assertEqual(result[1], 'http://b.jpg')


# ============================================================
# i2v 请求构建测试
# ============================================================
class TestBuildI2vRequest(unittest.TestCase):
    """测试 _build_i2v_request（图生视频）"""

    def setUp(self):
        self.driver = _create_driver(driver_type=28)

    def test_basic_i2v_request(self):
        """基本 i2v 请求结构"""
        ai_tool = _make_ai_tool(
            prompt='一只猫在跳舞',
            image_path='http://example.com/first.jpg',
            duration=5
        )
        # Mock get_first_last_frames 返回首帧
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls), \
             patch.object(self.driver, 'get_audio_path', return_value=None), \
             patch.object(self.driver, 'get_video_path', return_value=None):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertIn('json', result)
        self.assertEqual(result['method'], 'POST')
        self.assertIn('/services/aigc/video-generation/video-synthesis', result['url'])
        self.assertEqual(result['headers']['X-DashScope-Async'], 'enable')
        self.assertIn('Bearer', result['headers']['Authorization'])

        payload = result['json']
        self.assertEqual(payload['model'], 'happyhorse-1.0-i2v')
        self.assertEqual(payload['input']['prompt'], '一只猫在跳舞')
        self.assertEqual(payload['parameters']['duration'], 5)
        self.assertFalse(payload['parameters']['watermark'])

        # media 列表仅有首帧
        media = payload['input']['media']
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]['type'], 'first_frame')

    def test_i2v_with_audio_and_video(self):
        """i2v 请求包含驱动音频和视频"""
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            duration=10,
            audio_path='http://example.com/audio.wav',
            video_path='http://example.com/video.mp4'
        )
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls), \
             patch.object(self.driver, 'get_audio_path',
                          return_value='http://example.com/audio.wav'), \
             patch.object(self.driver, 'get_video_path',
                          return_value='http://example.com/video.mp4'), \
             patch.object(self.driver, '_validate_audio', return_value=(True, None)):
            result = self.driver._build_i2v_request(ai_tool)

        media = result['json']['input']['media']
        types = [m['type'] for m in media]
        self.assertIn('first_frame', types)
        self.assertIn('driving_audio', types)
        self.assertIn('driving_video', types)

    def test_i2v_no_first_frame_returns_error(self):
        """缺少首帧返回错误"""
        ai_tool = _make_ai_tool(image_path=None)
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=(None, None)):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertIn('首帧', result['error'])

    def test_i2v_audio_validation_failure(self):
        """音频校验失败返回错误"""
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            audio_path='http://example.com/bad.aac'
        )
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls), \
             patch.object(self.driver, 'get_audio_path',
                          return_value='http://example.com/bad.aac'), \
             patch.object(self.driver, '_validate_audio',
                          return_value=(False, '音频格式不支持')):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertIn('音频格式不支持', result['error'])

    def test_i2v_duration_clamped(self):
        """duration 超出范围时被修正为 5"""
        ai_tool = _make_ai_tool(image_path='http://example.com/first.jpg', duration=100)
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls), \
             patch.object(self.driver, 'get_audio_path', return_value=None), \
             patch.object(self.driver, 'get_video_path', return_value=None):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertEqual(result['json']['parameters']['duration'], 5)

    def test_i2v_with_seed(self):
        """seed 参数正确传递"""
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            extra_config={'seed': 12345}
        )
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls), \
             patch.object(self.driver, 'get_audio_path', return_value=None), \
             patch.object(self.driver, 'get_video_path', return_value=None):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertEqual(result['json']['parameters']['seed'], 12345)


# ============================================================
# r2v 请求构建测试
# ============================================================
class TestBuildR2vRequest(unittest.TestCase):
    """测试 _build_r2v_request（参考生视频）"""

    def setUp(self):
        self.driver = _create_driver(driver_type=29)

    def test_basic_r2v_request(self):
        """基本 r2v 请求结构"""
        ai_tool = _make_ai_tool(
            prompt='生成视频',
            image_path='http://example.com/ref1.jpg,http://example.com/ref2.jpg',
            duration=5,
            ratio='16:9'
        )
        with patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = self.driver._build_r2v_request(ai_tool)

        self.assertIn('json', result)
        payload = result['json']
        self.assertEqual(payload['model'], 'happyhorse-1.0-i2v')
        self.assertEqual(payload['parameters']['ratio'], '16:9')
        self.assertEqual(payload['parameters']['duration'], 5)

        media = payload['input']['media']
        self.assertEqual(len(media), 2)
        self.assertEqual(media[0]['type'], 'reference_image')
        self.assertEqual(media[1]['type'], 'reference_image')

    def test_r2v_no_images_returns_error(self):
        """缺少参考图返回错误"""
        ai_tool = _make_ai_tool(image_path=None, reference_images=None)
        result = self.driver._build_r2v_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertIn('参考图片', result['error'])

    def test_r2v_max_9_images(self):
        """超过 9 张图片时截取前 9 张"""
        images = ','.join([f'http://example.com/img{i}.jpg' for i in range(12)])
        ai_tool = _make_ai_tool(image_path=images)

        with patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = self.driver._build_r2v_request(ai_tool)

        media = result['json']['input']['media']
        self.assertEqual(len(media), 9)

    def test_r2v_invalid_ratio_clamped(self):
        """无效 ratio 被修正为默认值"""
        ai_tool = _make_ai_tool(
            image_path='http://example.com/ref.jpg',
            ratio='21:9'
        )
        with patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = self.driver._build_r2v_request(ai_tool)

        self.assertEqual(result['json']['parameters']['ratio'], '16:9')

    def test_r2v_from_reference_images_json(self):
        """从 reference_images JSON 读取"""
        ai_tool = _make_ai_tool(
            image_path=None,
            reference_images=json.dumps(['http://example.com/a.jpg', 'http://example.com/b.jpg'])
        )
        with patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = self.driver._build_r2v_request(ai_tool)

        media = result['json']['input']['media']
        self.assertEqual(len(media), 2)


# ============================================================
# t2v 请求构建测试
# ============================================================
class TestBuildT2vRequest(unittest.TestCase):
    """测试 _build_t2v_request（文生视频）"""

    def setUp(self):
        self.driver = _create_driver(driver_type=30)

    def test_basic_t2v_request(self):
        """基本 t2v 请求结构"""
        ai_tool = _make_ai_tool(
            prompt='一只狗在奔跑',
            duration=5,
            ratio='9:16'
        )
        result = self.driver._build_t2v_request(ai_tool)

        self.assertIn('json', result)
        payload = result['json']
        self.assertEqual(payload['model'], 'happyhorse-1.0-i2v')
        self.assertEqual(payload['input']['prompt'], '一只狗在奔跑')
        self.assertEqual(payload['parameters']['duration'], 5)
        self.assertEqual(payload['parameters']['ratio'], '9:16')
        # t2v 没有 media 字段
        self.assertNotIn('media', payload['input'])

    def test_t2v_no_image_or_audio(self):
        """t2v 不需要图片和音频"""
        ai_tool = _make_ai_tool(
            prompt='文生视频测试',
            image_path=None,
            audio_path=None,
            video_path=None
        )
        result = self.driver._build_t2v_request(ai_tool)

        payload = result['json']
        self.assertNotIn('media', payload['input'])

    def test_t2v_default_watermark_false(self):
        """t2v 默认不加水印"""
        ai_tool = _make_ai_tool(prompt='测试')
        result = self.driver._build_t2v_request(ai_tool)

        self.assertFalse(result['json']['parameters']['watermark'])

    def test_t2v_ratio_options(self):
        """t2v 支持的 ratio 选项"""
        for ratio in ['16:9', '9:16', '1:1', '4:3', '3:4']:
            ai_tool = _make_ai_tool(prompt='测试', ratio=ratio)
            result = self.driver._build_t2v_request(ai_tool)
            self.assertEqual(result['json']['parameters']['ratio'], ratio,
                             f"ratio {ratio} 应被支持")

    def test_t2v_invalid_ratio_clamped(self):
        """无效 ratio 被修正"""
        ai_tool = _make_ai_tool(prompt='测试', ratio='2:35')
        result = self.driver._build_t2v_request(ai_tool)

        self.assertEqual(result['json']['parameters']['ratio'], '16:9')

    def test_t2v_duration_clamped(self):
        """超出范围的 duration 被修正"""
        ai_tool = _make_ai_tool(prompt='测试', duration=1)
        result = self.driver._build_t2v_request(ai_tool)

        self.assertEqual(result['json']['parameters']['duration'], 5)


# ============================================================
# build_create_request 分发测试
# ============================================================
class TestBuildCreateRequestDispatch(unittest.TestCase):
    """测试 build_create_request 根据 driver_type 分发"""

    def test_type_28_dispatches_to_i2v(self):
        """type=28 调用 _build_i2v_request"""
        driver = _create_driver(driver_type=28)
        ai_tool = _make_ai_tool()
        with patch.object(driver, '_build_i2v_request', return_value={'mocked': True}) as mock_i2v:
            driver.build_create_request(ai_tool)
            mock_i2v.assert_called_once_with(ai_tool)

    def test_type_29_dispatches_to_r2v(self):
        """type=29 调用 _build_r2v_request"""
        driver = _create_driver(driver_type=29)
        ai_tool = _make_ai_tool()
        with patch.object(driver, '_build_r2v_request', return_value={'mocked': True}) as mock_r2v:
            driver.build_create_request(ai_tool)
            mock_r2v.assert_called_once_with(ai_tool)

    def test_type_30_dispatches_to_t2v(self):
        """type=30 调用 _build_t2v_request"""
        driver = _create_driver(driver_type=30)
        ai_tool = _make_ai_tool()
        with patch.object(driver, '_build_t2v_request', return_value={'mocked': True}) as mock_t2v:
            driver.build_create_request(ai_tool)
            mock_t2v.assert_called_once_with(ai_tool)


# ============================================================
# build_check_query 测试
# ============================================================
class TestBuildCheckQuery(unittest.TestCase):
    """测试 build_check_query 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_check_query_structure(self):
        """验证查询请求结构"""
        result = self.driver.build_check_query("task-abc-123")
        self.assertEqual(result['method'], 'GET')
        self.assertIn('/api/v1/tasks/task-abc-123', result['url'])
        self.assertIn('Authorization', result['headers'])
        self.assertIn('Bearer test_api_key', result['headers']['Authorization'])


# ============================================================
# submit_task 测试
# ============================================================
class TestSubmitTask(unittest.TestCase):
    """测试 submit_task 流程"""

    def test_i2v_missing_first_frame(self):
        """i2v 缺少首帧返回错误"""
        driver = _create_driver(driver_type=28)
        ai_tool = _make_ai_tool(image_path=None)
        with patch.object(driver, 'get_first_last_frames', return_value=(None, None)):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertFalse(result['retry'])
        self.assertIn('首帧', result['error'])

    def test_r2v_missing_images(self):
        """r2v 缺少参考图返回错误"""
        driver = _create_driver(driver_type=29)
        ai_tool = _make_ai_tool(image_path=None, reference_images=None)
        result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertIn('参考图片', result['error'])

    def test_t2v_empty_prompt(self):
        """t2v 提示词为空返回错误"""
        driver = _create_driver(driver_type=30)
        ai_tool = _make_ai_tool(prompt='')
        result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertIn('提示词', result['error'])

    def test_t2v_success(self):
        """t2v 成功提交"""
        driver = _create_driver(driver_type=30)
        ai_tool = _make_ai_tool(prompt='一只猫在跳舞', duration=5, ratio='16:9')
        with patch.object(driver, '_request', return_value={
            "output": {"task_status": "PENDING", "task_id": "task-123"}
        }):
            result = driver.submit_task(ai_tool)

        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'task-123')

    def test_i2v_network_error_retry(self):
        """i2v 网络错误返回 retry=True"""
        driver = _create_driver(driver_type=28)
        ai_tool = _make_ai_tool(image_path='http://example.com/first.jpg')
        with patch.object(driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(driver, 'get_audio_path', return_value=None), \
             patch.object(driver, 'get_video_path', return_value=None), \
             patch.object(driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls), \
             patch.object(driver, '_request', side_effect=ConnectionError("timeout")):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])

    def test_api_error_response(self):
        """API 返回业务错误"""
        driver = _create_driver(driver_type=30)
        ai_tool = _make_ai_tool(prompt='测试')
        with patch.object(driver, '_request', return_value={
            "error": {"message": "InvalidParameter"}
        }):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertIn('InvalidParameter', result['error'])

    def test_api_missing_task_id(self):
        """API 响应缺少 task_id"""
        driver = _create_driver(driver_type=30)
        ai_tool = _make_ai_tool(prompt='测试')
        with patch.object(driver, '_request', return_value={
            "output": {"task_status": "PENDING"}
        }):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'SYSTEM')

    def test_i2v_build_failure_propagated(self):
        """build_create_request 返回错误时直接传播"""
        driver = _create_driver(driver_type=28)
        ai_tool = _make_ai_tool(image_path=None)
        with patch.object(driver, 'get_first_last_frames', return_value=(None, None)):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertIn('首帧', result['error'])


# ============================================================
# check_status 测试
# ============================================================
class TestCheckStatus(unittest.TestCase):
    """测试 check_status 状态映射"""

    def setUp(self):
        self.driver = _create_driver()

    def test_succeeded_with_video_url(self):
        """SUCCEEDED + video_url -> SUCCESS"""
        with patch.object(self.driver, '_request', return_value={
            "output": {"task_id": "xxx", "task_status": "SUCCEEDED",
                       "video_url": "https://cdn.example.com/video.mp4"}
        }):
            result = self.driver.check_status('task-123')
            self.assertEqual(result['status'], 'SUCCESS')
            self.assertEqual(result['result_url'], 'https://cdn.example.com/video.mp4')

    def test_succeeded_without_video_url(self):
        """SUCCEEDED 但无 video_url -> FAILED"""
        with patch.object(self.driver, '_request', return_value={
            "output": {"task_id": "xxx", "task_status": "SUCCEEDED"}
        }):
            result = self.driver.check_status('task-123')
            self.assertEqual(result['status'], 'FAILED')

    def test_failed_status(self):
        """FAILED -> FAILED"""
        with patch.object(self.driver, '_request', return_value={
            "output": {"task_id": "xxx", "task_status": "FAILED",
                       "code": "ERROR", "message": "内容审核不通过"}
        }):
            result = self.driver.check_status('task-123')
            self.assertEqual(result['status'], 'FAILED')
            self.assertIn('审核', result['error'])

    def test_canceled_status(self):
        """CANCELED -> FAILED"""
        with patch.object(self.driver, '_request', return_value={
            "output": {"task_id": "xxx", "task_status": "CANCELED"}
        }):
            result = self.driver.check_status('task-123')
            self.assertEqual(result['status'], 'FAILED')
            self.assertIn('取消', result['error'])

    def test_unknown_status(self):
        """UNKNOWN -> FAILED"""
        with patch.object(self.driver, '_request', return_value={
            "output": {"task_id": "xxx", "task_status": "UNKNOWN"}
        }):
            result = self.driver.check_status('task-123')
            self.assertEqual(result['status'], 'FAILED')

    def test_pending_status(self):
        """PENDING -> RUNNING"""
        with patch.object(self.driver, '_request', return_value={
            "output": {"task_id": "xxx", "task_status": "PENDING"}
        }):
            result = self.driver.check_status('task-123')
            self.assertEqual(result['status'], 'RUNNING')

    def test_running_status(self):
        """RUNNING -> RUNNING"""
        with patch.object(self.driver, '_request', return_value={
            "output": {"task_id": "xxx", "task_status": "RUNNING"}
        }):
            result = self.driver.check_status('task-123')
            self.assertEqual(result['status'], 'RUNNING')

    def test_network_error_returns_running(self):
        """网络异常返回 RUNNING（允许重试）"""
        with patch.object(self.driver, '_request', side_effect=ConnectionError("timeout")):
            result = self.driver.check_status('task-123')
            self.assertEqual(result['status'], 'RUNNING')

    def test_api_error_in_response(self):
        """响应包含 error 字段 -> FAILED"""
        with patch.object(self.driver, '_request', return_value={
            "error": {"message": "RateLimitExceeded"}
        }):
            result = self.driver.check_status('task-123')
            self.assertEqual(result['status'], 'FAILED')
            self.assertIn('RateLimitExceeded', result['error'])

    def test_invalid_response_format(self):
        """无效响应格式 -> FAILED (SYSTEM)"""
        with patch.object(self.driver, '_request', return_value="invalid"):
            result = self.driver.check_status('task-123')
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['error_type'], 'SYSTEM')


# ============================================================
# 音频校验测试
# ============================================================
class TestValidateAudio(unittest.TestCase):
    """测试 _validate_audio 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_none_audio_passes(self):
        """无音频文件直接通过"""
        is_valid, error = self.driver._validate_audio(None, 5)
        self.assertTrue(is_valid)

    def test_unsupported_format(self):
        """不支持的音频格式"""
        is_valid, error = self.driver._validate_audio('/path/to/audio.aac', 5)
        self.assertFalse(is_valid)
        self.assertIn('aac', error)

    def test_wav_format_accepted(self):
        """wav 格式被接受"""
        with patch.object(self.driver, '_get_audio_duration', return_value=5.0), \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1024):
            is_valid, error = self.driver._validate_audio('/path/to/audio.wav', 5)
            self.assertTrue(is_valid)

    def test_mp3_format_accepted(self):
        """mp3 格式被接受"""
        with patch.object(self.driver, '_get_audio_duration', return_value=5.0), \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1024):
            is_valid, error = self.driver._validate_audio('/path/to/audio.mp3', 5)
            self.assertTrue(is_valid)

    def test_audio_too_short(self):
        """音频时长过短"""
        with patch.object(self.driver, '_get_audio_duration', return_value=1.0), \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1024):
            is_valid, error = self.driver._validate_audio('/path/to/audio.wav', 5)
            self.assertFalse(is_valid)
            self.assertIn('过短', error)

    def test_audio_too_long(self):
        """音频时长过长"""
        with patch.object(self.driver, '_get_audio_duration', return_value=35.0), \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1024):
            is_valid, error = self.driver._validate_audio('/path/to/audio.wav', 5)
            self.assertFalse(is_valid)
            self.assertIn('过长', error)

    def test_audio_file_too_large(self):
        """音频文件过大"""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=20 * 1024 * 1024):  # 20MB
            is_valid, error = self.driver._validate_audio('/path/to/audio.wav', 5)
            self.assertFalse(is_valid)
            self.assertIn('过大', error)


# ============================================================
# 子类实例化测试
# ============================================================
class TestSubclassDrivers(unittest.TestCase):
    """测试子类实例化"""

    def test_r2v_subclass(self):
        """R2V 子类"""
        from task.visual_drivers.happy_horse_dashscope_v1_driver import HappyHorseDashscopeR2VV1Driver
        with patch('task.visual_drivers.happy_horse_dashscope_v1_driver.get_dynamic_config_value') as mock_config, \
             patch('task.visual_drivers.happy_horse_dashscope_v1_driver.get_config', return_value={}):

            def side_effect(*keys, default=None):
                key_map = {
                    ('llm', 'qwen', 'api_key'): 'test_key',
                    ('timeout', 'request_timeout'): 30,
                    ('server', 'is_local'): False,
                }
                return key_map.get(keys, default)

            mock_config.side_effect = side_effect
            driver = HappyHorseDashscopeR2VV1Driver()
            self.assertEqual(driver.driver_name, 'happy_horse_dashscope_r2v_v1')
            self.assertEqual(driver.driver_type, 29)
            self.assertEqual(driver.MODEL, 'happyhorse-1.0-r2v')

    def test_t2v_subclass(self):
        """T2V 子类"""
        from task.visual_drivers.happy_horse_dashscope_v1_driver import HappyHorseDashscopeT2VV1Driver
        with patch('task.visual_drivers.happy_horse_dashscope_v1_driver.get_dynamic_config_value') as mock_config, \
             patch('task.visual_drivers.happy_horse_dashscope_v1_driver.get_config', return_value={}):

            def side_effect(*keys, default=None):
                key_map = {
                    ('llm', 'qwen', 'api_key'): 'test_key',
                    ('timeout', 'request_timeout'): 30,
                    ('server', 'is_local'): False,
                }
                return key_map.get(keys, default)

            mock_config.side_effect = side_effect
            driver = HappyHorseDashscopeT2VV1Driver()
            self.assertEqual(driver.driver_name, 'happy_horse_dashscope_t2v_v1')
            self.assertEqual(driver.driver_type, 30)
            self.assertEqual(driver.MODEL, 'happyhorse-1.0-t2v')


if __name__ == '__main__':
    unittest.main()
