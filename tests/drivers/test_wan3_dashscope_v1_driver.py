"""
Wan3.0 阿里云百炼驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

测试覆盖：
- 三种驱动模式初始化（i2v/r2v/t2v）及配置缺失校验
- 响应格式验证（submit_response / status_response）
- i2v 请求构建（首帧 / 首+尾帧 / 缺首帧）
- r2v 请求构建（参考图+参考视频+参考音频、时长校验）
- t2v 请求构建（仅提示词）
- extra_config 参数解析
- submit_task 流程（成功/业务错误/格式异常/网络异常）
- check_status 状态映射
- 6 个驱动类的 MODEL / driver_type / driver_name
"""
import json
import unittest
from unittest.mock import patch, MagicMock

from tests.base.test_isolation import stub_modules

# Mock 外部依赖（在 import driver 之前；stub 随 with 块结束自动恢复，
# driver 模块导入后已缓存，继续持有 stub 模块的属性引用）
with stub_modules({
    'utils.sentry_util': MagicMock(),
    'utils.image_upload_utils': MagicMock(),
    'api.media': MagicMock(),
}):
    from task.visual_drivers.wan3_dashscope_v1_driver import (
        Wan3DashscopeV1Driver,
        Wan3DashscopeR2VV1Driver,
        Wan3DashscopeT2VV1Driver,
        Wan3VideoPrimeDashscopeV1Driver,
        Wan3VideoPrimeDashscopeR2VV1Driver,
        Wan3VideoPrimeDashscopeT2VV1Driver,
    )
from task.visual_drivers.base_video_driver import DriverConfigError


def _create_driver(driver_type=40, driver_name="wan3_video_dashscope_v1",
                   api_key='test_api_key', workspace_id='test-ws',
                   region='cn-beijing'):
    """创建 Wan3DashscopeV1Driver 实例（mock 所有外部依赖）"""
    with patch('task.visual_drivers.wan3_dashscope_v1_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.wan3_dashscope_v1_driver.get_config', return_value={}):

        def side_effect(*keys, default=None):
            key_map = {
                ('llm', 'qwen', 'api_key'): api_key,
                ('wan3', 'workspace_id'): workspace_id,
                ('wan3', 'endpoint_region'): region,
                ('timeout', 'request_timeout'): 30,
            }
            return key_map.get(keys, default)

        mock_config.side_effect = side_effect
        driver = Wan3DashscopeV1Driver(driver_name=driver_name, driver_type=driver_type)
        return driver


def _create_subclass_driver(cls, **config_overrides):
    """创建子类驱动实例（mock 配置读取）"""
    key_map = {
        ('llm', 'qwen', 'api_key'): 'test_api_key',
        ('wan3', 'workspace_id'): 'test-ws',
        ('wan3', 'endpoint_region'): 'cn-beijing',
        ('timeout', 'request_timeout'): 30,
    }
    key_map.update(config_overrides)

    with patch('task.visual_drivers.wan3_dashscope_v1_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.wan3_dashscope_v1_driver.get_config', return_value={}):
        mock_config.side_effect = lambda *keys, default=None: key_map.get(keys, default)
        return cls()


def _make_ai_tool(prompt='测试提示词', image_path='http://example.com/first.jpg',
                  extra_config=None, duration=5, ratio='adaptive',
                  reference_images=None, audio_path=None, video_path=None):
    """创建模拟的 ai_tool 对象"""
    tool = MagicMock()
    tool.id = 3001
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
class TestWan3DriverInit(unittest.TestCase):
    """测试驱动初始化"""

    def test_i2v_default_init(self):
        """i2v 模式默认初始化"""
        driver = _create_driver(driver_type=40)
        self.assertEqual(driver.driver_type, 40)
        self.assertEqual(driver._api_key, 'test_api_key')
        self.assertEqual(driver._workspace_id, 'test-ws')
        self.assertEqual(driver._base_url, 'https://test-ws.cn-beijing.maas.aliyuncs.com/api/v1')
        self.assertEqual(driver.MODEL, 'wan3.0-video')

    def test_r2v_driver_type(self):
        """r2v 模式 driver_type=41"""
        driver = _create_driver(driver_type=41, driver_name='wan3_video_dashscope_r2v_v1')
        self.assertEqual(driver.driver_type, 41)

    def test_t2v_driver_type(self):
        """t2v 模式 driver_type=39"""
        driver = _create_driver(driver_type=39, driver_name='wan3_video_dashscope_t2v_v1')
        self.assertEqual(driver.driver_type, 39)

    def test_custom_region_base_url(self):
        """自定义地域正确拼装 base_url"""
        driver = _create_driver(region='ap-southeast-1')
        self.assertEqual(driver._base_url, 'https://test-ws.ap-southeast-1.maas.aliyuncs.com/api/v1')

    def test_missing_api_key_raises(self):
        """API Key 为空时抛出异常"""
        with patch('task.visual_drivers.wan3_dashscope_v1_driver.get_dynamic_config_value',
                   return_value=''), \
             patch('task.visual_drivers.wan3_dashscope_v1_driver.get_config', return_value={}):
            with self.assertRaises(DriverConfigError):
                Wan3DashscopeV1Driver()

    def test_missing_workspace_id_raises(self):
        """业务空间 ID 为空且 base_url 无法解析时抛出异常"""
        def side_effect(*keys, default=None):
            if keys == ('wan3', 'workspace_id'):
                return ''
            if keys == ('llm', 'qwen', 'api_key'):
                return 'test_api_key'
            return default

        with patch('task.visual_drivers.wan3_dashscope_v1_driver.get_dynamic_config_value',
                   side_effect=side_effect), \
             patch('task.visual_drivers.wan3_dashscope_v1_driver.get_config', return_value={}):
            with self.assertRaises(DriverConfigError):
                Wan3DashscopeV1Driver()

    def test_workspace_derived_from_maas_base_url(self):
        """未配置 workspace_id 时，从 llm.qwen.base_url 的 maas 域名自动解析"""
        def side_effect(*keys, default=None):
            key_map = {
                ('llm', 'qwen', 'api_key'): 'test_api_key',
                ('llm', 'qwen', 'base_url'): 'https://llm-nqvx1sbyyhmh3olj.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
                ('wan3', 'workspace_id'): '',
                ('wan3', 'endpoint_region'): '',
                ('timeout', 'request_timeout'): 30,
            }
            return key_map.get(keys, default)

        with patch('task.visual_drivers.wan3_dashscope_v1_driver.get_dynamic_config_value',
                   side_effect=side_effect), \
             patch('task.visual_drivers.wan3_dashscope_v1_driver.get_config', return_value={}):
            driver = Wan3DashscopeV1Driver()
            self.assertEqual(driver._workspace_id, 'llm-nqvx1sbyyhmh3olj')
            self.assertEqual(driver._region, 'cn-beijing')
            self.assertEqual(
                driver._base_url,
                'https://llm-nqvx1sbyyhmh3olj.cn-beijing.maas.aliyuncs.com/api/v1'
            )

    def test_workspace_derived_region_from_host(self):
        """从 maas 域名同时解析地域（如新加坡）"""
        def side_effect(*keys, default=None):
            key_map = {
                ('llm', 'qwen', 'api_key'): 'test_api_key',
                ('llm', 'qwen', 'base_url'): 'llm-abc123.ap-southeast-1.maas.aliyuncs.com',
                ('wan3', 'workspace_id'): '',
                ('wan3', 'endpoint_region'): '',
                ('timeout', 'request_timeout'): 30,
            }
            return key_map.get(keys, default)

        with patch('task.visual_drivers.wan3_dashscope_v1_driver.get_dynamic_config_value',
                   side_effect=side_effect), \
             patch('task.visual_drivers.wan3_dashscope_v1_driver.get_config', return_value={}):
            driver = Wan3DashscopeV1Driver()
            self.assertEqual(driver._workspace_id, 'llm-abc123')
            self.assertEqual(driver._region, 'ap-southeast-1')

    def test_explicit_workspace_id_takes_precedence(self):
        """显式配置 wan3.workspace_id 优先于 base_url 解析"""
        def side_effect(*keys, default=None):
            key_map = {
                ('llm', 'qwen', 'api_key'): 'test_api_key',
                ('llm', 'qwen', 'base_url'): 'https://llm-xxx.cn-beijing.maas.aliyuncs.com',
                ('wan3', 'workspace_id'): 'explicit-ws',
                ('wan3', 'endpoint_region'): 'eu-central-1',
                ('timeout', 'request_timeout'): 30,
            }
            return key_map.get(keys, default)

        with patch('task.visual_drivers.wan3_dashscope_v1_driver.get_dynamic_config_value',
                   side_effect=side_effect), \
             patch('task.visual_drivers.wan3_dashscope_v1_driver.get_config', return_value={}):
            driver = Wan3DashscopeV1Driver()
            self.assertEqual(driver._workspace_id, 'explicit-ws')
            self.assertEqual(driver._region, 'eu-central-1')

    def test_classic_dashscope_base_url_not_parsed(self):
        """经典 dashscope 域名无法解析业务空间，仍抛配置异常"""
        def side_effect(*keys, default=None):
            key_map = {
                ('llm', 'qwen', 'api_key'): 'test_api_key',
                ('llm', 'qwen', 'base_url'): 'https://dashscope.aliyuncs.com',
                ('wan3', 'workspace_id'): '',
                ('wan3', 'endpoint_region'): '',
                ('timeout', 'request_timeout'): 30,
            }
            return key_map.get(keys, default)

        with patch('task.visual_drivers.wan3_dashscope_v1_driver.get_dynamic_config_value',
                   side_effect=side_effect), \
             patch('task.visual_drivers.wan3_dashscope_v1_driver.get_config', return_value={}):
            with self.assertRaises(DriverConfigError):
                Wan3DashscopeV1Driver()


# ============================================================
# 响应验证测试
# ============================================================
class TestValidateSubmitResponse(unittest.TestCase):
    """测试 _validate_submit_response 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_valid_response(self):
        """正确格式的 submit 响应"""
        result = {"output": {"task_status": "PENDING", "task_id": "abc-123"}, "request_id": "r1"}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_response_with_code_field(self):
        """包含 code 字段的失败响应视为格式有效"""
        result = {"code": "InvalidParameter", "message": "bad param", "request_id": "r1"}
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

    def test_response_with_code_field(self):
        """包含 code 字段视为有效"""
        result = {"code": "Throttling", "message": "rate limit"}
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
        self.assertEqual(result['resolution'], '1080P')
        self.assertTrue(result['audio'])
        self.assertFalse(result['watermark'])
        self.assertTrue(result['prompt_extend'])
        self.assertNotIn('seed', result)

    def test_json_string_config(self):
        """JSON 字符串格式 extra_config"""
        ai_tool = _make_ai_tool(extra_config=json.dumps({
            'video_resolution': '720P',
            'audio': False,
            'watermark': True,
            'seed': 42,
            'prompt_extend': False
        }))
        result = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(result['resolution'], '720P')
        self.assertFalse(result['audio'])
        self.assertTrue(result['watermark'])
        self.assertEqual(result['seed'], 42)
        self.assertFalse(result['prompt_extend'])

    def test_legacy_resolution_key(self):
        """兼容旧 resolution 字段"""
        ai_tool = _make_ai_tool(extra_config={'resolution': '480P'})
        result = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(result['resolution'], '480P')

    def test_video_resolution_preferred_over_legacy(self):
        """优先使用 video_resolution，兼容旧 resolution 字段"""
        ai_tool = _make_ai_tool(extra_config={
            'resolution': '480P',
            'video_resolution': '1080P',
        })
        result = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(result['resolution'], '1080P')

    def test_invalid_resolution_ignored(self):
        """无效的 resolution 值被忽略，使用默认值"""
        ai_tool = _make_ai_tool(extra_config={'video_resolution': '4K'})
        result = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(result['resolution'], '1080P')

    def test_seed_out_of_range_ignored(self):
        """超出范围的 seed 被忽略"""
        ai_tool = _make_ai_tool(extra_config={'seed': 9999999999})
        result = self.driver._parse_extra_params(ai_tool)
        self.assertNotIn('seed', result)

    def test_invalid_json_string(self):
        """无效 JSON 字符串使用默认值"""
        ai_tool = _make_ai_tool(extra_config='not json')
        result = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(result['resolution'], '1080P')


# ============================================================
# i2v 请求构建测试
# ============================================================
class TestBuildI2vRequest(unittest.TestCase):
    """测试 _build_i2v_request（图生视频）"""

    def setUp(self):
        self.driver = _create_driver(driver_type=40)

    def test_basic_i2v_request(self):
        """仅首帧的 i2v 请求结构"""
        ai_tool = _make_ai_tool(
            prompt='一只猫在跳舞',
            image_path='http://example.com/first.jpg',
            duration=5
        )
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertIn('json', result)
        self.assertEqual(result['method'], 'POST')
        self.assertIn('/services/aigc/video-generation/video-synthesis', result['url'])
        self.assertEqual(result['headers']['X-DashScope-Async'], 'enable')
        self.assertIn('Bearer', result['headers']['Authorization'])
        self.assertEqual(result['headers']['Content-Type'], 'application/json')

        payload = result['json']
        self.assertEqual(payload['model'], 'wan3.0-video')
        self.assertEqual(payload['input']['prompt'], '一只猫在跳舞')
        self.assertEqual(payload['parameters']['duration'], 5)
        self.assertEqual(payload['parameters']['resolution'], '1080P')
        self.assertEqual(payload['parameters']['ratio'], 'adaptive')
        self.assertTrue(payload['parameters']['audio'])
        self.assertFalse(payload['parameters']['watermark'])
        self.assertTrue(payload['parameters']['prompt_extend'])

        media = payload['input']['media']
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]['type'], 'first_frame')
        self.assertEqual(media[0]['url'], 'http://example.com/first.jpg')

    def test_i2v_with_first_and_last_frame(self):
        """首帧+尾帧的 i2v 请求"""
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg,http://example.com/last.jpg'
        )
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', 'http://example.com/last.jpg')), \
             patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = self.driver._build_i2v_request(ai_tool)

        media = result['json']['input']['media']
        self.assertEqual(len(media), 2)
        self.assertEqual(media[0]['type'], 'first_frame')
        self.assertEqual(media[1]['type'], 'last_frame')
        self.assertEqual(media[1]['url'], 'http://example.com/last.jpg')

    def test_i2v_no_first_frame_returns_error(self):
        """缺少首帧返回 USER 错误"""
        ai_tool = _make_ai_tool(image_path=None)
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=(None, None)):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertFalse(result['retry'])
        self.assertIn('首帧', result['error'])

    def test_i2v_duration_clamped(self):
        """duration 超出 2-30 范围时被修正为 5"""
        ai_tool = _make_ai_tool(image_path='http://example.com/first.jpg', duration=100)
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertEqual(result['json']['parameters']['duration'], 5)

    def test_i2v_with_seed_and_params(self):
        """seed / audio / watermark / prompt_extend 参数正确传递"""
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg',
            ratio='9:16',
            extra_config={'seed': 12345, 'audio': False, 'watermark': True, 'prompt_extend': False}
        )
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = self.driver._build_i2v_request(ai_tool)

        params = result['json']['parameters']
        self.assertEqual(params['seed'], 12345)
        self.assertEqual(params['ratio'], '9:16')
        self.assertFalse(params['audio'])
        self.assertTrue(params['watermark'])
        self.assertFalse(params['prompt_extend'])

    def test_i2v_invalid_ratio_falls_back_to_adaptive(self):
        """无效 ratio 回退为 adaptive"""
        ai_tool = _make_ai_tool(image_path='http://example.com/first.jpg', ratio='21:9')
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertEqual(result['json']['parameters']['ratio'], 'adaptive')


# ============================================================
# r2v 请求构建测试
# ============================================================
class TestBuildR2vRequest(unittest.TestCase):
    """测试 _build_r2v_request（参考生视频）"""

    def setUp(self):
        self.driver = _create_driver(driver_type=41)

    def test_r2v_with_image_video_audio(self):
        """参考图+参考视频+参考音频的 media 顺序与类型"""
        ai_tool = _make_ai_tool(
            prompt='参考生成',
            image_path='http://example.com/ref1.jpg,http://example.com/ref2.jpg',
            video_path='http://example.com/v1.mp4',
            audio_path='http://example.com/a1.mp3',
            duration=5
        )
        with patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls), \
             patch('task.visual_drivers.wan3_dashscope_v1_driver._get_media_duration_seconds',
                   return_value=3.0):
            result = self.driver._build_r2v_request(ai_tool)

        media = result['json']['input']['media']
        types = [m['type'] for m in media]
        self.assertEqual(types, ['reference_image', 'reference_image', 'reference_video', 'reference_audio'])
        self.assertEqual(media[2]['url'], 'http://example.com/v1.mp4')
        self.assertEqual(media[3]['url'], 'http://example.com/a1.mp3')

    def test_r2v_multi_videos_comma_separated(self):
        """video_path 逗号分隔多段参考视频"""
        ai_tool = _make_ai_tool(
            prompt='参考生成',
            image_path=None,
            reference_images=None,
            video_path='http://example.com/v1.mp4, http://example.com/v2.mp4',
            duration=5
        )
        with patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls), \
             patch('task.visual_drivers.wan3_dashscope_v1_driver._get_media_duration_seconds',
                   return_value=3.0):
            result = self.driver._build_r2v_request(ai_tool)

        media = result['json']['input']['media']
        types = [m['type'] for m in media]
        self.assertEqual(types, ['reference_video', 'reference_video'])

    def test_r2v_duration_limit_exceeded(self):
        """输入视频总时长+输出时长>30 返回 USER 错误"""
        ai_tool = _make_ai_tool(
            prompt='参考生成',
            image_path=None,
            video_path='http://example.com/v1.mp4,http://example.com/v2.mp4',
            duration=15
        )
        with patch('task.visual_drivers.wan3_dashscope_v1_driver._get_media_duration_seconds',
                   return_value=10.0):
            result = self.driver._build_r2v_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertIn('30秒', result['error'])

    def test_r2v_no_media_no_prompt_returns_error(self):
        """无任何参考素材且无提示词返回 USER 错误"""
        ai_tool = _make_ai_tool(prompt='', image_path=None, reference_images=None,
                                audio_path=None, video_path=None)
        result = self.driver._build_r2v_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')

    def test_r2v_from_reference_images_json(self):
        """从 reference_images JSON 读取参考图"""
        ai_tool = _make_ai_tool(
            image_path=None,
            reference_images=json.dumps(['http://example.com/a.jpg', 'http://example.com/b.jpg'])
        )
        with patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = self.driver._build_r2v_request(ai_tool)

        media = result['json']['input']['media']
        self.assertEqual(len(media), 2)
        self.assertEqual(media[0]['type'], 'reference_image')

    def test_r2v_max_10_images(self):
        """超过 10 张参考图时截取前 10 张"""
        images = ','.join([f'http://example.com/img{i}.jpg' for i in range(12)])
        ai_tool = _make_ai_tool(image_path=images)
        with patch.object(self.driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = self.driver._build_r2v_request(ai_tool)

        media = result['json']['input']['media']
        self.assertEqual(len(media), 10)


# ============================================================
# t2v 请求构建测试
# ============================================================
class TestBuildT2vRequest(unittest.TestCase):
    """测试 _build_t2v_request（文生视频）"""

    def setUp(self):
        self.driver = _create_driver(driver_type=39)

    def test_basic_t2v_request(self):
        """纯 prompt，无 media 字段"""
        ai_tool = _make_ai_tool(prompt='一只狗在奔跑', duration=8, ratio='16:9')
        result = self.driver._build_t2v_request(ai_tool)

        self.assertIn('json', result)
        payload = result['json']
        self.assertEqual(payload['model'], 'wan3.0-video')
        self.assertEqual(payload['input']['prompt'], '一只狗在奔跑')
        self.assertNotIn('media', payload['input'])
        self.assertEqual(payload['parameters']['duration'], 8)
        self.assertEqual(payload['parameters']['ratio'], '16:9')

    def test_t2v_empty_prompt_returns_error(self):
        """空提示词返回 USER 错误"""
        ai_tool = _make_ai_tool(prompt='   ')
        result = self.driver._build_t2v_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertIn('提示词', result['error'])

    def test_t2v_invalid_ratio_falls_back_to_adaptive(self):
        """无效 ratio 回退为 adaptive"""
        ai_tool = _make_ai_tool(prompt='测试', ratio='2:35')
        result = self.driver._build_t2v_request(ai_tool)

        self.assertEqual(result['json']['parameters']['ratio'], 'adaptive')


# ============================================================
# build_create_request 分发测试
# ============================================================
class TestBuildCreateRequestDispatch(unittest.TestCase):
    """测试 build_create_request 根据 driver_type 分发"""

    def test_type_40_dispatches_to_i2v(self):
        """type=40 调用 _build_i2v_request"""
        driver = _create_driver(driver_type=40)
        ai_tool = _make_ai_tool()
        with patch.object(driver, '_build_i2v_request', return_value={'mocked': True}) as mock_i2v:
            driver.build_create_request(ai_tool)
            mock_i2v.assert_called_once_with(ai_tool)

    def test_type_41_dispatches_to_r2v(self):
        """type=41 调用 _build_r2v_request"""
        driver = _create_driver(driver_type=41)
        ai_tool = _make_ai_tool()
        with patch.object(driver, '_build_r2v_request', return_value={'mocked': True}) as mock_r2v:
            driver.build_create_request(ai_tool)
            mock_r2v.assert_called_once_with(ai_tool)

    def test_type_39_dispatches_to_t2v(self):
        """type=39 调用 _build_t2v_request"""
        driver = _create_driver(driver_type=39)
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
        """验证查询请求结构（仅 Authorization 头）"""
        result = self.driver.build_check_query("task-abc-123")
        self.assertEqual(result['method'], 'GET')
        self.assertEqual(
            result['url'],
            'https://test-ws.cn-beijing.maas.aliyuncs.com/api/v1/tasks/task-abc-123'
        )
        self.assertIn('Bearer test_api_key', result['headers']['Authorization'])
        self.assertNotIn('X-DashScope-Async', result['headers'])


# ============================================================
# submit_task 测试
# ============================================================
class TestSubmitTask(unittest.TestCase):
    """测试 submit_task 流程"""

    def test_i2v_missing_first_frame(self):
        """i2v 缺少首帧返回错误"""
        driver = _create_driver(driver_type=40)
        ai_tool = _make_ai_tool(image_path=None)
        with patch.object(driver, 'get_first_last_frames', return_value=(None, None)):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertFalse(result['retry'])
        self.assertIn('首帧', result['error'])

    def test_r2v_missing_media_and_prompt(self):
        """r2v 缺少参考素材和提示词返回错误"""
        driver = _create_driver(driver_type=41)
        ai_tool = _make_ai_tool(prompt='', image_path=None, reference_images=None,
                                audio_path=None, video_path=None)
        result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertIn('参考素材', result['error'])

    def test_t2v_empty_prompt(self):
        """t2v 提示词为空返回错误"""
        driver = _create_driver(driver_type=39)
        ai_tool = _make_ai_tool(prompt='')
        result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertIn('提示词', result['error'])

    def test_t2v_success(self):
        """t2v 成功提交返回 project_id"""
        driver = _create_driver(driver_type=39)
        ai_tool = _make_ai_tool(prompt='一只猫在跳舞', duration=5, ratio='16:9')
        with patch.object(driver, '_request', return_value={
            "output": {"task_status": "PENDING", "task_id": "task-123"},
            "request_id": "r1"
        }):
            result = driver.submit_task(ai_tool)

        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'task-123')

    def test_api_business_error(self):
        """API 业务错误（code/message）返回失败"""
        driver = _create_driver(driver_type=39)
        ai_tool = _make_ai_tool(prompt='测试', duration=5)
        with patch.object(driver, '_request', return_value={
            "code": "InvalidParameter",
            "message": "duration 不合法",
            "request_id": "r1"
        }):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertIn('duration 不合法', result['error'])

    def test_invalid_response_format(self):
        """响应格式异常返回 SYSTEM 错误"""
        driver = _create_driver(driver_type=39)
        ai_tool = _make_ai_tool(prompt='测试', duration=5)
        with patch.object(driver, '_request', return_value={"request_id": "r1"}):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'SYSTEM')

    def test_network_error_retry(self):
        """网络错误返回 retry=True"""
        driver = _create_driver(driver_type=39)
        ai_tool = _make_ai_tool(prompt='测试', duration=5)
        with patch.object(driver, '_request', side_effect=ConnectionError("timeout")):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])


# ============================================================
# check_status 测试
# ============================================================
class TestCheckStatus(unittest.TestCase):
    """测试 check_status 状态映射"""

    def setUp(self):
        self.driver = _create_driver()

    def _check(self, response):
        with patch.object(self.driver, '_request', return_value=response):
            return self.driver.check_status("task-123")

    def test_succeeded_with_video_url(self):
        """SUCCEEDED + video_url → SUCCESS"""
        result = self._check({
            "output": {"task_id": "task-123", "task_status": "SUCCEEDED",
                       "video_url": "http://example.com/result.mp4"}
        })
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'http://example.com/result.mp4')

    def test_succeeded_without_video_url(self):
        """SUCCEEDED 但无 video_url → FAILED"""
        result = self._check({
            "output": {"task_id": "task-123", "task_status": "SUCCEEDED"}
        })
        self.assertEqual(result['status'], 'FAILED')

    def test_pending_maps_to_running(self):
        """PENDING → RUNNING"""
        result = self._check({"output": {"task_id": "task-123", "task_status": "PENDING"}})
        self.assertEqual(result['status'], 'RUNNING')

    def test_running_maps_to_running(self):
        """RUNNING → RUNNING"""
        result = self._check({"output": {"task_id": "task-123", "task_status": "RUNNING"}})
        self.assertEqual(result['status'], 'RUNNING')

    def test_failed_with_output_code_message(self):
        """FAILED → FAILED，取 output 内 code/message"""
        result = self._check({
            "output": {"task_id": "task-123", "task_status": "FAILED",
                       "code": "ContentFiltered", "message": "内容审核未通过"}
        })
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('内容审核未通过', result['error'])

    def test_canceled_maps_to_failed(self):
        """CANCELED → FAILED"""
        result = self._check({"output": {"task_id": "task-123", "task_status": "CANCELED"}})
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('取消', result['error'])

    def test_unknown_maps_to_failed(self):
        """UNKNOWN → FAILED"""
        result = self._check({"output": {"task_id": "task-123", "task_status": "UNKNOWN"}})
        self.assertEqual(result['status'], 'FAILED')

    def test_top_level_code_maps_to_failed(self):
        """顶层 code/message 业务错误 → FAILED"""
        result = self._check({"code": "Throttling", "message": "rate limit"})
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('rate limit', result['error'])

    def test_invalid_response_format(self):
        """响应格式异常 → FAILED SYSTEM"""
        result = self._check({"request_id": "r1"})
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error_type'], 'SYSTEM')

    def test_network_error_keeps_running(self):
        """网络异常保持 RUNNING 等待重试"""
        with patch.object(self.driver, '_request', side_effect=ConnectionError("timeout")):
            result = self.driver.check_status("task-123")
        self.assertEqual(result['status'], 'RUNNING')


# ============================================================
# 子类定义测试
# ============================================================
class TestSubclasses(unittest.TestCase):
    """测试 6 个驱动类的 MODEL / driver_type / driver_name"""

    def test_standard_i2v(self):
        driver = _create_subclass_driver(Wan3DashscopeV1Driver)
        self.assertEqual(driver.MODEL, 'wan3.0-video')
        self.assertEqual(driver.driver_type, 40)
        self.assertEqual(driver.driver_name, 'wan3_video_dashscope_v1')

    def test_standard_r2v(self):
        driver = _create_subclass_driver(Wan3DashscopeR2VV1Driver)
        self.assertEqual(driver.MODEL, 'wan3.0-video')
        self.assertEqual(driver.driver_type, 41)
        self.assertEqual(driver.driver_name, 'wan3_video_dashscope_r2v_v1')

    def test_standard_t2v(self):
        driver = _create_subclass_driver(Wan3DashscopeT2VV1Driver)
        self.assertEqual(driver.MODEL, 'wan3.0-video')
        self.assertEqual(driver.driver_type, 39)
        self.assertEqual(driver.driver_name, 'wan3_video_dashscope_t2v_v1')

    def test_prime_i2v(self):
        driver = _create_subclass_driver(Wan3VideoPrimeDashscopeV1Driver)
        self.assertEqual(driver.MODEL, 'wan3.0-video-prime')
        self.assertEqual(driver.driver_type, 40)
        self.assertEqual(driver.driver_name, 'wan3_video_prime_dashscope_v1')

    def test_prime_r2v(self):
        driver = _create_subclass_driver(Wan3VideoPrimeDashscopeR2VV1Driver)
        self.assertEqual(driver.MODEL, 'wan3.0-video-prime')
        self.assertEqual(driver.driver_type, 41)
        self.assertEqual(driver.driver_name, 'wan3_video_prime_dashscope_r2v_v1')

    def test_prime_t2v(self):
        driver = _create_subclass_driver(Wan3VideoPrimeDashscopeT2VV1Driver)
        self.assertEqual(driver.MODEL, 'wan3.0-video-prime')
        self.assertEqual(driver.driver_type, 39)
        self.assertEqual(driver.driver_name, 'wan3_video_prime_dashscope_t2v_v1')

    def test_prime_r2v_builds_r2v_request(self):
        """高速版 r2v 子类构建请求使用 prime 模型且走 r2v 分支"""
        driver = _create_subclass_driver(Wan3VideoPrimeDashscopeR2VV1Driver)
        ai_tool = _make_ai_tool(prompt='参考生成', image_path='http://example.com/ref.jpg')
        with patch.object(driver, '_upload_media_to_cdn',
                          side_effect=lambda urls, t: urls):
            result = driver.build_create_request(ai_tool)

        payload = result['json']
        self.assertEqual(payload['model'], 'wan3.0-video-prime')
        self.assertEqual(payload['input']['media'][0]['type'], 'reference_image')


if __name__ == '__main__':
    unittest.main()
