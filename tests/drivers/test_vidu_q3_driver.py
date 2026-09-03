"""
Vidu Q3 官方驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

测试覆盖：
- 驱动初始化及 vidu.token 缺失校验
- i2v 请求构建（1 图 img2video / 2 图 start-end2video / 缺图 / 无 aspect_ratio）
- t2v 请求构建（纯 prompt / aspect_ratio 下发 / 空 prompt）
- r2v 请求构建（参考图合并去重 / 超 7 张截断 / pro 模型名 viduq3 / 缺图）
- extra_config 参数解析（resolution 小写映射 / audio+audio_type / seed/watermark/off_peak）
- submit_task 流程（成功/业务错误/网络异常）
- check_status 状态映射
- 6 个驱动类的 driver_type / MODEL_* 属性
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
}):
    from task.visual_drivers.vidu_q3_driver import (
        ViduQ3TurboV1Driver,
        ViduQ3TurboR2VV1Driver,
        ViduQ3TurboT2VV1Driver,
        ViduQ3ProV1Driver,
        ViduQ3ProR2VV1Driver,
        ViduQ3ProT2VV1Driver,
    )
from task.visual_drivers.base_video_driver import DriverConfigError


def _create_driver(driver_type=43, driver_name="vidu_q3_i2v_turbo_v1",
                   api_key='test_vidu_token'):
    """创建 ViduQ3TurboV1Driver 实例（mock 所有外部依赖）"""
    key_map = {
        ('vidu', 'token'): api_key,
        ('timeout', 'request_timeout'): 30,
    }
    with patch('task.visual_drivers.vidu_q3_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.vidu_q3_driver.get_config', return_value={}):
        mock_config.side_effect = lambda *keys, default=None: key_map.get(keys, default)
        return ViduQ3TurboV1Driver(driver_name=driver_name, driver_type=driver_type)


def _create_subclass_driver(cls, api_key='test_vidu_token'):
    """创建子类驱动实例（mock 配置读取）"""
    key_map = {
        ('vidu', 'token'): api_key,
        ('timeout', 'request_timeout'): 30,
    }
    with patch('task.visual_drivers.vidu_q3_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.vidu_q3_driver.get_config', return_value={}):
        mock_config.side_effect = lambda *keys, default=None: key_map.get(keys, default)
        return cls()


def _make_ai_tool(prompt='测试提示词', image_path='http://example.com/first.jpg',
                  extra_config=None, duration=5, ratio='16:9',
                  reference_images=None):
    """创建模拟的 ai_tool 对象"""
    tool = MagicMock()
    tool.id = 4001
    tool.prompt = prompt
    tool.image_path = image_path
    tool.extra_config = extra_config
    tool.duration = duration
    tool.ratio = ratio
    tool.reference_images = reference_images
    return tool


# ============================================================
# 驱动初始化测试
# ============================================================
class TestViduQ3DriverInit(unittest.TestCase):
    """测试驱动初始化"""

    def test_default_init(self):
        """默认初始化（i2v turbo）"""
        driver = _create_driver()
        self.assertEqual(driver.driver_type, 43)
        self.assertEqual(driver.driver_name, 'vidu_q3_i2v_turbo_v1')
        self.assertEqual(driver._api_key, 'test_vidu_token')
        self.assertEqual(driver._base_url, 'https://api.vidu.cn')

    def test_missing_token_raises(self):
        """vidu.token 为空时抛出 DriverConfigError"""
        with self.assertRaises(DriverConfigError):
            _create_driver(api_key='')

    def test_authorization_header_uses_token_scheme(self):
        """认证头使用 Token 方案（非 Bearer）"""
        driver = _create_driver()
        query = driver.build_check_query("task-123")
        self.assertEqual(query['headers']['Authorization'], 'Token test_vidu_token')
        self.assertEqual(
            query['url'],
            'https://api.vidu.cn/ent/v2/tasks/task-123/creations'
        )


# ============================================================
# i2v 请求构建测试
# ============================================================
class TestBuildI2vRequest(unittest.TestCase):
    """测试 _build_i2v_request（图生视频）"""

    def setUp(self):
        self.driver = _create_driver(driver_type=43)

    def test_single_image_uses_img2video(self):
        """1 张图片走 img2video 端点"""
        ai_tool = _make_ai_tool(image_path='http://example.com/first.jpg')
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertEqual(result['url'], 'https://api.vidu.cn/ent/v2/img2video')
        payload = result['json']
        self.assertEqual(payload['model'], 'viduq3-turbo')
        self.assertEqual(payload['images'], ['http://example.com/first.jpg'])
        self.assertEqual(payload['duration'], 5)
        self.assertNotIn('aspect_ratio', payload)

    def test_two_images_uses_start_end2video(self):
        """2 张图片走 start-end2video，images 顺序为首+尾"""
        ai_tool = _make_ai_tool(
            image_path='http://example.com/first.jpg,http://example.com/last.jpg'
        )
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', 'http://example.com/last.jpg')), \
             patch.object(self.driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertEqual(result['url'], 'https://api.vidu.cn/ent/v2/start-end2video')
        payload = result['json']
        self.assertEqual(payload['images'],
                         ['http://example.com/first.jpg', 'http://example.com/last.jpg'])
        self.assertNotIn('aspect_ratio', payload)

    def test_no_image_returns_user_error(self):
        """缺少首帧返回 USER 错误"""
        ai_tool = _make_ai_tool(image_path=None)
        with patch.object(self.driver, 'get_first_last_frames', return_value=(None, None)):
            result = self.driver._build_i2v_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertFalse(result['retry'])
        self.assertIn('首帧', result['error'])

    def test_q3_forbidden_params_not_sent(self):
        """q3 不生效的参数禁止下发"""
        ai_tool = _make_ai_tool()
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
            result = self.driver._build_i2v_request(ai_tool)

        payload = result['json']
        for forbidden in ('movement_amplitude', 'style', 'bgm', 'voice_id', 'aspect_ratio'):
            self.assertNotIn(forbidden, payload)


# ============================================================
# t2v 请求构建测试
# ============================================================
class TestBuildT2vRequest(unittest.TestCase):
    """测试 _build_t2v_request（文生视频）"""

    def setUp(self):
        self.driver = _create_driver(driver_type=42, driver_name='vidu_q3_t2v_turbo_v1')

    def test_basic_t2v_request(self):
        """纯 prompt，aspect_ratio 正确下发"""
        ai_tool = _make_ai_tool(prompt='一只猫在跳舞', ratio='9:16', duration=8)
        result = self.driver._build_t2v_request(ai_tool)

        self.assertEqual(result['url'], 'https://api.vidu.cn/ent/v2/text2video')
        payload = result['json']
        self.assertEqual(payload['model'], 'viduq3-turbo')
        self.assertEqual(payload['prompt'], '一只猫在跳舞')
        self.assertEqual(payload['aspect_ratio'], '9:16')
        self.assertEqual(payload['duration'], 8)
        self.assertNotIn('images', payload)

    def test_t2v_invalid_ratio_falls_back(self):
        """无效 ratio 回退为 16:9"""
        ai_tool = _make_ai_tool(prompt='测试', ratio='21:9')
        result = self.driver._build_t2v_request(ai_tool)

        self.assertEqual(result['json']['aspect_ratio'], '16:9')

    def test_t2v_empty_prompt_returns_user_error(self):
        """空提示词返回 USER 错误"""
        ai_tool = _make_ai_tool(prompt='   ')
        result = self.driver._build_t2v_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertIn('提示词', result['error'])


# ============================================================
# r2v 请求构建测试
# ============================================================
class TestBuildR2vRequest(unittest.TestCase):
    """测试 _build_r2v_request（参考生视频）"""

    def setUp(self):
        self.driver = _create_driver(driver_type=44, driver_name='vidu_q3_r2v_turbo_v1')

    def test_r2v_merges_and_dedupes_images(self):
        """合并 image_path 与 reference_images 并去重"""
        ai_tool = _make_ai_tool(
            prompt='参考生成',
            image_path='http://example.com/a.jpg,http://example.com/b.jpg',
            reference_images=json.dumps(['http://example.com/b.jpg', 'http://example.com/c.jpg'])
        )
        with patch.object(self.driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
            result = self.driver._build_r2v_request(ai_tool)

        self.assertEqual(result['url'], 'https://api.vidu.cn/ent/v2/reference2video')
        payload = result['json']
        self.assertEqual(payload['model'], 'viduq3-turbo')
        self.assertEqual(payload['images'], [
            'http://example.com/a.jpg',
            'http://example.com/b.jpg',
            'http://example.com/c.jpg',
        ])

    def test_r2v_truncates_over_7_images(self):
        """超过 7 张参考图时截取前 7 张"""
        images = ','.join([f'http://example.com/img{i}.jpg' for i in range(10)])
        ai_tool = _make_ai_tool(prompt='参考生成', image_path=images)
        with patch.object(self.driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
            result = self.driver._build_r2v_request(ai_tool)

        self.assertEqual(len(result['json']['images']), 7)

    def test_r2v_pro_model_name_is_viduq3(self):
        """pro 实现 reference2video 模型名为 viduq3（非 viduq3-pro）"""
        driver = _create_subclass_driver(ViduQ3ProR2VV1Driver)
        ai_tool = _make_ai_tool(prompt='参考生成', image_path='http://example.com/a.jpg')
        with patch.object(driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
            result = driver._build_r2v_request(ai_tool)

        self.assertEqual(result['json']['model'], 'viduq3')

    def test_r2v_no_image_returns_user_error(self):
        """缺少参考图返回 USER 错误"""
        ai_tool = _make_ai_tool(prompt='参考生成', image_path=None, reference_images=None)
        result = self.driver._build_r2v_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertIn('参考图', result['error'])

    def test_r2v_empty_prompt_returns_user_error(self):
        """r2v 提示词必填"""
        ai_tool = _make_ai_tool(prompt='', image_path='http://example.com/a.jpg')
        result = self.driver._build_r2v_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')

    def test_r2v_duration_clamped_min_3(self):
        """r2v duration 下限为 3，越界回退默认 5"""
        ai_tool = _make_ai_tool(prompt='参考生成', image_path='http://example.com/a.jpg', duration=2)
        with patch.object(self.driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
            result = self.driver._build_r2v_request(ai_tool)

        self.assertEqual(result['json']['duration'], 5)

    def test_r2v_ratio_restricted(self):
        """r2v 比例仅支持 16:9/9:16/1:1，其余回退 16:9"""
        ai_tool = _make_ai_tool(prompt='参考生成', image_path='http://example.com/a.jpg', ratio='4:3')
        with patch.object(self.driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
            result = self.driver._build_r2v_request(ai_tool)

        self.assertEqual(result['json']['aspect_ratio'], '16:9')


# ============================================================
# extra_config 参数解析测试
# ============================================================
class TestParseExtraParams(unittest.TestCase):
    """测试 _parse_extra_params 与公共参数下发"""

    def setUp(self):
        self.driver = _create_driver()

    def test_default_resolution_and_audio(self):
        """无 extra_config 时 resolution=720p、audio=True 且带 audio_type"""
        ai_tool = _make_ai_tool(extra_config=None)
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
            result = self.driver._build_i2v_request(ai_tool)

        payload = result['json']
        self.assertEqual(payload['resolution'], '720p')
        self.assertTrue(payload['audio'])
        self.assertEqual(payload['audio_type'], 'all')

    def test_resolution_lowercase_mapping(self):
        """resolution 标准值映射为小写下发值"""
        for std, driver_value in (('540P', '540p'), ('720P', '720p'), ('1080P', '1080p')):
            ai_tool = _make_ai_tool(extra_config={'video_resolution': std})
            with patch.object(self.driver, 'get_first_last_frames',
                              return_value=('http://example.com/first.jpg', None)), \
                 patch.object(self.driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
                result = self.driver._build_i2v_request(ai_tool)
            self.assertEqual(result['json']['resolution'], driver_value)

    def test_legacy_resolution_key(self):
        """兼容旧 resolution 字段"""
        ai_tool = _make_ai_tool(extra_config={'resolution': '1080P'})
        params = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(params['resolution'], '1080P')

    def test_invalid_resolution_falls_back(self):
        """无效 resolution 回退默认 720p"""
        ai_tool = _make_ai_tool(extra_config={'video_resolution': '4K'})
        params = self.driver._parse_extra_params(ai_tool)
        self.assertEqual(params['resolution'], '720P')

    def test_audio_false_omits_audio_type(self):
        """audio=False 时不下发 audio_type"""
        ai_tool = _make_ai_tool(extra_config={'audio': False})
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
            result = self.driver._build_i2v_request(ai_tool)

        payload = result['json']
        self.assertFalse(payload['audio'])
        self.assertNotIn('audio_type', payload)

    def test_seed_watermark_off_peak(self):
        """seed / watermark / off_peak 可选下发"""
        ai_tool = _make_ai_tool(extra_config={'seed': 123, 'watermark': True, 'off_peak': True})
        with patch.object(self.driver, 'get_first_last_frames',
                          return_value=('http://example.com/first.jpg', None)), \
             patch.object(self.driver, '_upload_images_to_cdn', side_effect=lambda urls: urls):
            result = self.driver._build_i2v_request(ai_tool)

        payload = result['json']
        self.assertEqual(payload['seed'], 123)
        self.assertTrue(payload['watermark'])
        self.assertTrue(payload['off_peak'])

    def test_seed_out_of_range_ignored(self):
        """超出范围的 seed 被忽略"""
        ai_tool = _make_ai_tool(extra_config={'seed': 9999999999})
        params = self.driver._parse_extra_params(ai_tool)
        self.assertNotIn('seed', params)


# ============================================================
# build_create_request 分发测试
# ============================================================
class TestBuildCreateRequestDispatch(unittest.TestCase):
    """测试 build_create_request 根据 driver_type 分发"""

    def test_type_43_dispatches_to_i2v(self):
        driver = _create_driver(driver_type=43)
        ai_tool = _make_ai_tool()
        with patch.object(driver, '_build_i2v_request', return_value={'mocked': True}) as mock_i2v:
            driver.build_create_request(ai_tool)
            mock_i2v.assert_called_once_with(ai_tool)

    def test_type_44_dispatches_to_r2v(self):
        driver = _create_driver(driver_type=44, driver_name='vidu_q3_r2v_turbo_v1')
        ai_tool = _make_ai_tool()
        with patch.object(driver, '_build_r2v_request', return_value={'mocked': True}) as mock_r2v:
            driver.build_create_request(ai_tool)
            mock_r2v.assert_called_once_with(ai_tool)

    def test_type_42_dispatches_to_t2v(self):
        driver = _create_driver(driver_type=42, driver_name='vidu_q3_t2v_turbo_v1')
        ai_tool = _make_ai_tool()
        with patch.object(driver, '_build_t2v_request', return_value={'mocked': True}) as mock_t2v:
            driver.build_create_request(ai_tool)
            mock_t2v.assert_called_once_with(ai_tool)


# ============================================================
# submit_task 测试
# ============================================================
class TestSubmitTask(unittest.TestCase):
    """测试 submit_task 流程"""

    def test_submit_success_returns_project_id(self):
        """成功提交返回 project_id"""
        driver = _create_driver(driver_type=42, driver_name='vidu_q3_t2v_turbo_v1')
        ai_tool = _make_ai_tool(prompt='一只猫在跳舞')
        with patch.object(driver, '_request', return_value={
            "task_id": "task_abc_123", "state": "created"
        }):
            result = driver.submit_task(ai_tool)

        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'task_abc_123')

    def test_submit_business_error(self):
        """API 业务错误返回失败"""
        driver = _create_driver(driver_type=42, driver_name='vidu_q3_t2v_turbo_v1')
        ai_tool = _make_ai_tool(prompt='测试')
        with patch.object(driver, '_request', return_value={"error": "prompt 审核未通过"}):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertFalse(result['retry'])

    def test_submit_invalid_response_format(self):
        """响应格式异常返回 SYSTEM 错误"""
        driver = _create_driver(driver_type=42, driver_name='vidu_q3_t2v_turbo_v1')
        ai_tool = _make_ai_tool(prompt='测试')
        with patch.object(driver, '_request', return_value={"unexpected": True}):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'SYSTEM')

    def test_submit_network_error_retry(self):
        """网络异常返回 retry=True"""
        driver = _create_driver(driver_type=42, driver_name='vidu_q3_t2v_turbo_v1')
        ai_tool = _make_ai_tool(prompt='测试')
        with patch.object(driver, '_request', side_effect=ConnectionError("timeout")):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])

    def test_submit_i2v_missing_image_returns_user_error(self):
        """i2v 缺图时 build 阶段即返回 USER 错误，不发请求"""
        driver = _create_driver(driver_type=43)
        ai_tool = _make_ai_tool(image_path=None)
        with patch.object(driver, 'get_first_last_frames', return_value=(None, None)), \
             patch.object(driver, '_request') as mock_request:
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        mock_request.assert_not_called()


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

    def test_created_maps_to_running(self):
        result = self._check({"id": "1", "state": "created", "creations": []})
        self.assertEqual(result['status'], 'RUNNING')

    def test_queueing_maps_to_running(self):
        result = self._check({"id": "1", "state": "queueing", "creations": []})
        self.assertEqual(result['status'], 'RUNNING')

    def test_processing_maps_to_running(self):
        result = self._check({"id": "1", "state": "processing", "creations": []})
        self.assertEqual(result['status'], 'RUNNING')

    def test_success_returns_result_url(self):
        """success → SUCCESS 且取 creations[0].url"""
        result = self._check({
            "id": "1", "state": "success",
            "creations": [{"url": "http://example.com/result.mp4"}]
        })
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'http://example.com/result.mp4')

    def test_success_without_creations_fails(self):
        result = self._check({"id": "1", "state": "success", "creations": []})
        self.assertEqual(result['status'], 'FAILED')

    def test_failed_returns_err_code(self):
        """failed → FAILED 且取 err_code"""
        result = self._check({"id": "1", "state": "failed", "creations": [], "err_code": "内容审核未通过"})
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error'], '内容审核未通过')

    def test_network_error_keeps_running(self):
        """网络异常保持 RUNNING 等待重试"""
        with patch.object(self.driver, '_request', side_effect=ConnectionError("timeout")):
            result = self.driver.check_status("task-123")
        self.assertEqual(result['status'], 'RUNNING')

    def test_invalid_response_format_fails(self):
        """响应格式异常 → FAILED SYSTEM"""
        result = self._check({"unexpected": True})
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error_type'], 'SYSTEM')


# ============================================================
# 子类定义测试
# ============================================================
class TestSubclasses(unittest.TestCase):
    """测试 6 个驱动类的 driver_type / MODEL_* / driver_name"""

    def test_turbo_i2v(self):
        driver = _create_subclass_driver(ViduQ3TurboV1Driver)
        self.assertEqual(driver.driver_type, 43)
        self.assertEqual(driver.driver_name, 'vidu_q3_i2v_turbo_v1')
        self.assertEqual(driver.MODEL_IMG2V, 'viduq3-turbo')
        self.assertEqual(driver.MODEL_SE2V, 'viduq3-turbo')
        self.assertEqual(driver.MODEL_T2V, 'viduq3-turbo')
        self.assertEqual(driver.MODEL_R2V, 'viduq3-turbo')

    def test_turbo_r2v(self):
        driver = _create_subclass_driver(ViduQ3TurboR2VV1Driver)
        self.assertEqual(driver.driver_type, 44)
        self.assertEqual(driver.driver_name, 'vidu_q3_r2v_turbo_v1')
        self.assertEqual(driver.MODEL_R2V, 'viduq3-turbo')

    def test_turbo_t2v(self):
        driver = _create_subclass_driver(ViduQ3TurboT2VV1Driver)
        self.assertEqual(driver.driver_type, 42)
        self.assertEqual(driver.driver_name, 'vidu_q3_t2v_turbo_v1')
        self.assertEqual(driver.MODEL_T2V, 'viduq3-turbo')

    def test_pro_i2v(self):
        driver = _create_subclass_driver(ViduQ3ProV1Driver)
        self.assertEqual(driver.driver_type, 43)
        self.assertEqual(driver.driver_name, 'vidu_q3_i2v_pro_v1')
        self.assertEqual(driver.MODEL_IMG2V, 'viduq3-pro')
        self.assertEqual(driver.MODEL_SE2V, 'viduq3-pro')
        self.assertEqual(driver.MODEL_T2V, 'viduq3-pro')
        self.assertEqual(driver.MODEL_R2V, 'viduq3')

    def test_pro_r2v(self):
        driver = _create_subclass_driver(ViduQ3ProR2VV1Driver)
        self.assertEqual(driver.driver_type, 44)
        self.assertEqual(driver.driver_name, 'vidu_q3_r2v_pro_v1')
        self.assertEqual(driver.MODEL_R2V, 'viduq3')

    def test_pro_t2v(self):
        driver = _create_subclass_driver(ViduQ3ProT2VV1Driver)
        self.assertEqual(driver.driver_type, 42)
        self.assertEqual(driver.driver_name, 'vidu_q3_t2v_pro_v1')
        self.assertEqual(driver.MODEL_T2V, 'viduq3-pro')

    def test_pro_t2v_builds_t2v_request_with_pro_model(self):
        """pro t2v 子类构建请求使用 viduq3-pro 且走 t2v 分支"""
        driver = _create_subclass_driver(ViduQ3ProT2VV1Driver)
        ai_tool = _make_ai_tool(prompt='一只猫在跳舞', ratio='1:1')
        result = driver.build_create_request(ai_tool)

        payload = result['json']
        self.assertEqual(payload['model'], 'viduq3-pro')
        self.assertEqual(payload['aspect_ratio'], '1:1')
        self.assertIn('/text2video', result['url'])


if __name__ == '__main__':
    unittest.main()
