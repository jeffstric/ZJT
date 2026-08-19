"""
Seedance huimengi 网关驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

测试覆盖：
- 3 个子类初始化（2.0 Fast / 2.0 / 2.0 Mini）
- build_create_request 四种模式：
    * 文生视频（纯文本，params 内无图片字段）
    * 首帧图生视频（params.image_url）
    * 首尾帧图生视频（params 内嵌 first_frame_image / last_frame_image）
    * 多参考图模式（params.reference_images）
- human_review 透传
- 响应校验（submit_response / status_response）
- submit_task：成功提取 task_id、HTTPError 400 内容审核、HTTPError 429 限流重试
- check_status：completed 取 result.video_url、failed 取 error_message、
                pending/processing → RUNNING、429 仍 RUNNING
- 配置默认值（base_url 不含尾部斜杠）
"""
import sys
import unittest
from unittest.mock import patch, MagicMock

# 防御：某些 driver_integration 测试会在模块级 `sys.modules['requests'] = MagicMock()`
# 全局污染 requests。本驱动的 submit_task/check_status 用 `except requests.exceptions.HTTPError`
# 捕获异常，若 requests 被 mock 成 MagicMock，except 会抛 TypeError（mock 不能作异常类），
# 导致异常掉进兜底分支返回 SYSTEM/FAILED。这里强制还原真实 requests，保证本测试可用。
import importlib
_req_mod = sys.modules.get('requests')
if _req_mod is None or not hasattr(_req_mod, 'exceptions') or \
        not isinstance(getattr(_req_mod.exceptions, 'HTTPError', None), type):
    sys.modules.pop('requests', None)
    importlib.import_module('requests')

# Mock 外部依赖（必须在 import driver 之前）
# 注意：
# - utils.content_moderation_error 不 mock，它只依赖标准库，需用真实逻辑校验
# - model.ai_tool_pipeline_steps 不 mock 全局（会污染其他真实依赖该模块的测试），
#   改为真实导入常量 + 局部 patch PipelineStepModel（参考火山版 seedance 测试写法）
# - utils.video_compressor 不 mock（火山版 seedance 测试真实依赖它，全局 mock 会污染）
sys.modules['utils.sentry_util'] = MagicMock()
sys.modules['utils.image_upload_utils'] = MagicMock()


def _ensure_real_requests():
    """确保 requests 是真实模块（而非被其他测试 mock 成的 MagicMock）。

    某些 driver_integration 测试会在模块级 `sys.modules['requests'] = MagicMock()`。
    这会导致两个层面的污染：
    1. sys.modules['requests'] 被替换
    2. 若本驱动模块在污染后才被 import，驱动顶部的 `import requests` 会把 MagicMock
       绑定到驱动模块的 requests 名字（模块加载只执行一次，后续还原 sys.modules 无效）

    本函数每次创建驱动前调用，同时修复这两个层面：还原 sys.modules，并强制重绑
    驱动模块的 requests 名字为真实模块，保证任意执行顺序下 except 都能正确捕获异常。
    """
    _req_mod = sys.modules.get('requests')
    http_error = getattr(getattr(_req_mod, 'exceptions', None), 'HTTPError', None)
    if not isinstance(http_error, type):
        sys.modules.pop('requests', None)
        sys.modules.pop('requests.exceptions', None)
        real_requests = importlib.import_module('requests')
        # 驱动模块若已加载，强制重绑其 requests 名字（修复模块加载时的污染绑定）
        drv_mod = sys.modules.get('task.visual_drivers.seedance_huimengi_v1_driver')
        if drv_mod is not None:
            drv_mod.requests = real_requests


def _create_driver(cls, api_key='test_huimengi_key'):
    """创建 huimengi 驱动实例（mock 所有外部依赖）"""
    _ensure_real_requests()
    with patch('task.visual_drivers.seedance_huimengi_v1_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.seedance_huimengi_v1_driver.get_config', return_value={}):

        def side_effect(*keys, default=None):
            key_map = {
                ('huimengi', 'api_key'): api_key,
                ('huimengi', 'base_url'): 'https://api.huimengi.com',
                ('timeout', 'request_timeout'): 30,
                ('server', 'is_local'): False,
                ('test_mode', 'enabled'): False,
                ('test_mode', 'mock_videos'): {},
            }
            return key_map.get(keys, default)

        mock_config.side_effect = side_effect
        driver = cls()
        return driver


def _make_ai_tool(prompt='测试提示词', image_path='http://example.com/first.jpg',
                  extra_config=None, duration=5, ratio='16:9',
                  reference_images=None, audio_path=None, video_path=None,
                  image_mode_declared=False):
    """创建模拟的 ai_tool 对象

    image_mode_declared: 是否在 extra_config 中声明 image_mode（影响文生视频判定）
    """
    tool = MagicMock()
    tool.id = 2001
    tool.prompt = prompt
    tool.image_path = image_path
    tool.duration = duration
    tool.ratio = ratio
    tool.audio_path = audio_path
    tool.video_path = video_path

    config = dict(extra_config or {})
    if image_mode_declared and 'image_mode' not in config:
        config['image_mode'] = 'first_last_frame'
    tool.extra_config = config
    return tool


def _stub_image_upload_success():
    """让 compress_and_upload_image_sync 返回成功"""
    mod = sys.modules['utils.image_upload_utils']
    mod.compress_and_upload_image_sync = MagicMock(return_value=(True, 'http://cdn.example.com/img.jpg', None))
    mod.upload_media_to_cdn_sync = MagicMock(return_value=(True, 'http://cdn.example.com/media.mp4', None))


def _stub_pipeline_steps_empty():
    """返回一个 patcher，让驱动模块的 PipelineStepModel.get_by_ai_tool_and_stage 返回空列表。

    用法：在 setUp 里 `self._step_patcher = _stub_pipeline_steps_empty()`，
    tearDown 里 `self._step_patcher.stop()`。
    局部 patch 驱动模块绑定，避免全局 mock model.ai_tool_pipeline_steps 污染其他测试。
    """
    from unittest.mock import patch as _patch
    patcher = _patch('task.visual_drivers.seedance_huimengi_v1_driver.PipelineStepModel')
    mock_model = patcher.start()
    mock_model.get_by_ai_tool_and_stage.return_value = []
    return patcher


# ============================================================
# 子类初始化测试
# ============================================================
class TestSeedanceHuimengiDriverInit(unittest.TestCase):
    """测试 4 个子类初始化"""

    def test_20_fast_init(self):
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance20FastHuimengiV1Driver
        driver = _create_driver(Seedance20FastHuimengiV1Driver)
        self.assertEqual(driver.driver_type, 22)
        self.assertEqual(driver._model, 'seedance-2.0-fast')
        self.assertEqual(driver._base_url, 'https://api.huimengi.com')
        self.assertEqual(driver._api_key, 'test_huimengi_key')

    def test_20_init(self):
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance20HuimengiV1Driver
        driver = _create_driver(Seedance20HuimengiV1Driver)
        self.assertEqual(driver.driver_type, 23)
        self.assertEqual(driver._model, 'seedance-2.0')

    def test_20_mini_init(self):
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance20MiniHuimengiV1Driver
        driver = _create_driver(Seedance20MiniHuimengiV1Driver)
        self.assertEqual(driver.driver_type, 31)
        self.assertEqual(driver._model, 'seedance-2.0-mini')

    def test_25_init(self):
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance25HuimengiV1Driver
        from config.unified_config import TaskTypeId, DriverImplementation
        driver = _create_driver(Seedance25HuimengiV1Driver)
        self.assertEqual(driver.driver_type, TaskTypeId.SEEDANCE_2_5_IMAGE_TO_VIDEO)
        self.assertEqual(driver._model, 'seedance-2.5')
        self.assertEqual(driver.driver_name, DriverImplementation.SEEDANCE_2_5_HUIMENGI_V1)
        self.assertEqual(driver._base_url, 'https://api.huimengi.com')

    def test_base_url_trailing_slash_stripped(self):
        """base_url 尾部斜杠应被去除"""
        with patch('task.visual_drivers.seedance_huimengi_v1_driver.get_dynamic_config_value') as mock_config, \
             patch('task.visual_drivers.seedance_huimengi_v1_driver.get_config', return_value={}):

            def side_effect(*keys, default=None):
                key_map = {
                    ('huimengi', 'api_key'): 'k',
                    ('huimengi', 'base_url'): 'https://api.huimengi.com/',
                    ('timeout', 'request_timeout'): 30,
                    ('server', 'is_local'): False,
                    ('test_mode', 'enabled'): False,
                    ('test_mode', 'mock_videos'): {},
                }
                return key_map.get(keys, default)

            mock_config.side_effect = side_effect
            from task.visual_drivers.seedance_huimengi_v1_driver import Seedance20HuimengiV1Driver
            driver = Seedance20HuimengiV1Driver()
            self.assertEqual(driver._base_url, 'https://api.huimengi.com')


# ============================================================
# build_create_request 测试
# ============================================================
class TestBuildCreateRequest(unittest.TestCase):
    """测试请求构建（4 种模式 + human_review）"""

    def setUp(self):
        _stub_image_upload_success()
        self._step_patcher = _stub_pipeline_steps_empty()

    def tearDown(self):
        self._step_patcher.stop()

    def _driver(self):
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance20HuimengiV1Driver
        return _create_driver(Seedance20HuimengiV1Driver)

    def test_text_to_video(self):
        """文生视频：params 仅 prompt + 控制字段，无图片字段"""
        driver = self._driver()
        # 无图片、无音视频、extra_config 无 image_mode
        ai_tool = _make_ai_tool(
            prompt='一只猫在海滩上漫步',
            image_path=None,
            extra_config={'generate_audio': True}
        )
        req = driver.build_create_request(ai_tool)

        self.assertEqual(req['method'], 'POST')
        self.assertEqual(req['url'], 'https://api.huimengi.com/api/v1/tasks')
        # huimengi 扁平结构：{ model, params }
        self.assertEqual(req['json']['model'], 'seedance-2.0')
        params = req['json']['params']
        self.assertEqual(params['prompt'], '一只猫在海滩上漫步')
        self.assertEqual(params['generate_audio'], True)
        self.assertEqual(params['duration'], 5)
        # 文生视频不应有图片字段
        self.assertNotIn('image_url', params)
        self.assertNotIn('first_frame_image', params)
        self.assertNotIn('reference_images', params)
        self.assertEqual(req['headers']['Authorization'], 'Bearer test_huimengi_key')

    def test_25_text_to_video_uses_seedance_2_5_model(self):
        """Seedance 2.5 文生视频：model 为 seedance-2.5，params 与官方 curl 对齐"""
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance25HuimengiV1Driver
        driver = _create_driver(Seedance25HuimengiV1Driver)
        ai_tool = _make_ai_tool(
            prompt='一只猫在海滩上漫步',
            image_path=None,
            extra_config={'generate_audio': True, 'video_resolution': '720P'}
        )
        req = driver.build_create_request(ai_tool)

        self.assertEqual(req['method'], 'POST')
        self.assertEqual(req['url'], 'https://api.huimengi.com/api/v1/tasks')
        self.assertEqual(req['json']['model'], 'seedance-2.5')
        params = req['json']['params']
        self.assertEqual(params['prompt'], '一只猫在海滩上漫步')
        self.assertEqual(params['duration'], 5)
        self.assertEqual(params['resolution'], '720p')
        self.assertEqual(params['generate_audio'], True)
        self.assertNotIn('image_url', params)
        self.assertNotIn('omni_reference_task_type', params)
        self.assertNotIn('webhook_url', req['json'])

    def test_25_reference_video_uses_adaptive_ratio_and_follow_duration(self):
        """2.5 + 参考视频：显式 omni_reference_task_type=edit，ratio=adaptive、duration=-1"""
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance25HuimengiV1Driver
        from task.visual_drivers import seedance_huimengi_v1_driver as drv_mod
        driver = _create_driver(Seedance25HuimengiV1Driver)
        ai_tool = _make_ai_tool(
            prompt='参考视频1的内容进行视频复刻',
            extra_config={'image_mode': 'multi_reference', 'ratio': '9:16'},
            duration=5,
            video_path='http://example.com/ref.mp4',
        )
        with patch.object(driver, 'get_all_images_by_mode', return_value={
            'mode': 'multi_reference',
            'first_frame': None,
            'last_frame': None,
            'reference_images': [],
        }), patch.object(drv_mod, 'prepare_seedance_reference_video_sync',
                          return_value=(True, 'http://example.com/ref.mp4', None, [])), \
             patch.object(drv_mod, 'upload_media_to_cdn_sync',
                          return_value=(True, 'http://cdn.example.com/ref.mp4', None)):
            req = driver.build_create_request(ai_tool)

        params = req['json']['params']
        self.assertEqual(req['json']['model'], 'seedance-2.5')
        self.assertEqual(params['omni_reference_task_type'], 'edit')
        self.assertEqual(params['ratio'], 'adaptive')
        self.assertEqual(params['duration'], -1)

    def test_25_reference_video_edit_uses_shared_predicate(self):
        """驱动 edit 判定必须走共享谓词（与计价层同源），不得内联条件"""
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance25HuimengiV1Driver
        from task.visual_drivers import seedance_huimengi_v1_driver as drv_mod
        driver = _create_driver(Seedance25HuimengiV1Driver)
        ai_tool = _make_ai_tool(
            prompt='参考视频编辑',
            extra_config={'image_mode': 'multi_reference', 'ratio': '9:16'},
            duration=5,
            video_path='http://example.com/ref.mp4',
        )
        with patch.object(driver, 'get_all_images_by_mode', return_value={
            'mode': 'multi_reference',
            'first_frame': None,
            'last_frame': None,
            'reference_images': [],
        }), patch.object(drv_mod, 'is_video_edit_billing_task', return_value=True) as mock_predicate, \
             patch.object(drv_mod, 'prepare_seedance_reference_video_sync',
                          return_value=(True, 'http://example.com/ref.mp4', None, [])), \
             patch.object(drv_mod, 'upload_media_to_cdn_sync',
                          return_value=(True, 'http://cdn.example.com/ref.mp4', None)):
            req = driver.build_create_request(ai_tool)

        mock_predicate.assert_called_once_with(
            driver.driver_type, 'http://example.com/ref.mp4'
        )
        self.assertEqual(req['json']['params']['omni_reference_task_type'], 'edit')

    def test_text_to_video_empty_prompt_rejected(self):
        """文生视频空 prompt 应返回错误"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='', image_path=None)
        result = driver.build_create_request(ai_tool)
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')

    def test_first_frame_only_uses_image_url(self):
        """仅首帧：params.image_url 字段，无 first_frame_image"""
        from task.visual_drivers import seedance_huimengi_v1_driver as drv_mod
        driver = self._driver()
        ai_tool = _make_ai_tool(
            prompt='女孩睁开眼',
            image_path='http://example.com/first.jpg',
            image_mode_declared=True
        )
        with patch.object(driver, 'get_all_images_by_mode', return_value={
            'mode': 'first_last_frame',
            'first_frame': 'http://example.com/first.jpg',
            'last_frame': None,
            'reference_images': []
        }), patch.object(drv_mod, 'compress_and_upload_image_sync',
                          return_value=(True, 'http://cdn.example.com/img.jpg', None)):
            req = driver.build_create_request(ai_tool)

        params = req['json']['params']
        self.assertEqual(params['image_url'], 'http://cdn.example.com/img.jpg')
        self.assertNotIn('first_frame_image', params)
        self.assertNotIn('last_frame_image', params)

    def test_first_last_frame_uses_params_fields(self):
        """首尾帧：params 内嵌 first_frame_image / last_frame_image"""
        from task.visual_drivers import seedance_huimengi_v1_driver as drv_mod
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='女孩睁开眼', image_mode_declared=True)
        with patch.object(driver, 'get_all_images_by_mode', return_value={
            'mode': 'first_last_frame',
            'first_frame': 'http://example.com/first.jpg',
            'last_frame': 'http://example.com/last.jpg',
            'reference_images': []
        }), patch.object(drv_mod, 'compress_and_upload_image_sync',
                          return_value=(True, 'http://cdn.example.com/img.jpg', None)):
            req = driver.build_create_request(ai_tool)

        params = req['json']['params']
        # 仅首帧时才用 image_url；首尾帧用 first/last_frame_image
        self.assertNotIn('image_url', params)
        self.assertEqual(params['first_frame_image'], 'http://cdn.example.com/img.jpg')
        self.assertEqual(params['last_frame_image'], 'http://cdn.example.com/img.jpg')

    def test_multi_reference_images(self):
        """多参考图：params.reference_images 列表"""
        from task.visual_drivers import seedance_huimengi_v1_driver as drv_mod
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='多参考图测试', image_mode_declared=True)
        with patch.object(driver, 'get_all_images_by_mode', return_value={
            'mode': 'multi_reference',
            'first_frame': None,
            'last_frame': None,
            'reference_images': ['http://example.com/a.jpg', 'http://example.com/b.jpg']
        }), patch.object(drv_mod, 'compress_and_upload_image_sync',
                          return_value=(True, 'http://cdn.example.com/ref.jpg', None)):
            req = driver.build_create_request(ai_tool)

        params = req['json']['params']
        self.assertNotIn('image_url', params)
        self.assertEqual(len(params['reference_images']), 2)
        self.assertNotIn('first_frame_image', params)

    def test_pure_audio_routes_to_multi_reference(self):
        """纯音频（无图无视频）：驱动兜底改判 multi_reference，params 含 reference_audios，
        不含 reference_images / image_url（覆盖 CLI、storyboard 等非 server 入口）"""
        from task.visual_drivers import seedance_huimengi_v1_driver as drv_mod
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='纯音频测试', image_path=None, image_mode_declared=False,
                                audio_path='http://example.com/a.mp3')
        with patch.object(drv_mod, 'upload_media_to_cdn_sync',
                          return_value=(True, 'http://cdn.example.com/a.mp3', None)):
            req = driver.build_create_request(ai_tool)

        params = req['json']['params']
        self.assertEqual(params['reference_audios'], ['http://cdn.example.com/a.mp3'])
        self.assertNotIn('reference_images', params)
        self.assertNotIn('image_url', params)

    def test_human_review_passthrough(self):
        """human_review 从 extra_config 透传到 params.human_review"""
        driver = self._driver()
        ai_tool = _make_ai_tool(
            prompt='真人审核测试',
            image_path=None,
            extra_config={'human_review': True}
        )
        req = driver.build_create_request(ai_tool)
        self.assertTrue(req['json']['params']['human_review'])

    def test_human_review_default_omitted(self):
        """extra_config 未声明 human_review 时，params 不含该字段"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='无审核', image_path=None)
        req = driver.build_create_request(ai_tool)
        self.assertNotIn('human_review', req['json']['params'])

    def test_resolution_mapping_lowercase(self):
        """resolution 经 SEEDANCE_DRIVER_VALUES 转为小写（480p/720p/1080p/4k）"""
        from config.constant import VIDEO_RESOLUTION_EXTRA_CONFIG_KEY
        driver = self._driver()
        ai_tool = _make_ai_tool(
            prompt='分辨率测试',
            image_path=None,
            extra_config={VIDEO_RESOLUTION_EXTRA_CONFIG_KEY: '720P'}
        )
        req = driver.build_create_request(ai_tool)
        self.assertEqual(req['json']['params']['resolution'], '720p')


# ============================================================
# 响应校验测试
# ============================================================
class TestResponseValidation(unittest.TestCase):
    """测试 _validate_submit_response / _validate_status_response"""

    def _driver(self):
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance20HuimengiV1Driver
        return _create_driver(Seedance20HuimengiV1Driver)

    def test_submit_valid_flat(self):
        """扁平式响应（huimengi 真实结构）：顶层 task_id 提取"""
        driver = self._driver()
        ok, err = driver._validate_submit_response({
            "task_id": "a820e1b8-fb15-4ec9-a13c-bdd1d4eb6679",
            "status": "pending"
        })
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_submit_valid_with_top_id_fallback(self):
        """无 task_id 时回退顶层 id"""
        driver = self._driver()
        ok, err = driver._validate_submit_response({"id": "abc-123", "status": "pending"})
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_submit_missing_task_id(self):
        """既无 task_id 也无 id：报缺少 task_id"""
        driver = self._driver()
        ok, err = driver._validate_submit_response({"status": "pending"})
        self.assertFalse(ok)
        self.assertIn("task_id", err)

    def test_extract_task_id_priority(self):
        """顶层 task_id 优先于 id"""
        driver = self._driver()
        # task_id 优先
        self.assertEqual(driver._extract_task_id({"task_id": "primary", "id": "secondary"}), "primary")
        # 无 task_id 时回退 id
        self.assertEqual(driver._extract_task_id({"id": "only_id"}), "only_id")
        # 都没有
        self.assertIsNone(driver._extract_task_id({"foo": "bar"}))

    def test_submit_error_body_structured(self):
        """结构化错误 {error:{message,code}}：返回 API 错误 [code]: message"""
        driver = self._driver()
        ok, err = driver._validate_submit_response({
            "error": {"message": "参数错误", "type": "validation_error", "code": "InvalidParam"}
        })
        self.assertFalse(ok)
        self.assertIn("参数错误", err)
        self.assertIn("InvalidParam", err)

    def test_submit_error_body_content_moderation(self):
        """审核类错误（content_filter）：返回带审核前缀的友好文案"""
        driver = self._driver()
        ok, err = driver._validate_submit_response({
            "error": {"message": "content blocked", "type": "safety", "code": "content_filter"}
        })
        self.assertFalse(ok)
        # 友好文案应包含审核相关字样（如"违规"/"敏感"等）
        self.assertTrue(
            any(kw in err for kw in ["违规", "敏感", "审核", "内容"]),
            f"err 应为审核友好文案，实际: {err}"
        )

    def test_submit_error_message_flat(self):
        """扁平错误 {error_message}：返回该文案"""
        driver = self._driver()
        ok, err = driver._validate_submit_response({"error_message": "余额不足"})
        self.assertFalse(ok)
        self.assertIn("余额不足", err)

    def test_status_valid_success(self):
        """查询响应：completed 状态有效"""
        driver = self._driver()
        ok, err = driver._validate_status_response({
            "id": "a820e1b8-...",
            "model": "seedance-2.0",
            "status": "completed",
            "result": {"video_url": "https://..."}
        })
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_status_valid_failed(self):
        """查询响应：failed 状态有效"""
        driver = self._driver()
        ok, err = driver._validate_status_response({
            "id": "a820e1b8-...",
            "status": "failed",
            "error_message": "内容违规",
            "cost": 0
        })
        self.assertTrue(ok)

    def test_status_missing_status(self):
        """查询响应缺少 status：报错"""
        driver = self._driver()
        ok, err = driver._validate_status_response({"id": "x"})
        self.assertFalse(ok)
        self.assertIn("status", err)

    def test_status_missing_id(self):
        """查询响应缺少 id/task_id：报错"""
        driver = self._driver()
        ok, err = driver._validate_status_response({"status": "completed"})
        self.assertFalse(ok)
        self.assertIn("id", err)


# ============================================================
# submit_task 流程测试
# ============================================================
class TestSubmitTask(unittest.TestCase):
    """测试提交任务流程"""

    def setUp(self):
        _stub_image_upload_success()
        self._step_patcher = _stub_pipeline_steps_empty()

    def tearDown(self):
        self._step_patcher.stop()

    def _driver(self):
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance20HuimengiV1Driver
        return _create_driver(Seedance20HuimengiV1Driver)

    def test_submit_success_extracts_task_id(self):
        """成功响应：从顶层 task_id 提取"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='一只猫在海滩上漫步', image_path=None)
        with patch.object(driver, '_request', return_value={
            "task_id": "a820e1b8-fb15-4ec9-a13c-bdd1d4eb6679",
            "status": "pending"
        }):
            result = driver.submit_task(ai_tool)

        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'a820e1b8-fb15-4ec9-a13c-bdd1d4eb6679')

    def test_submit_http_400_content_moderation(self):
        """HTTP 400 内容审核错误：返回 USER 错误不重试"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='文生视频测试', image_path=None)

        fake_resp = MagicMock()
        fake_resp.status_code = 400
        # content_filter 是审核类 code，会触发 format_user_facing_moderation_error 返回友好文案
        fake_resp.json.return_value = {"error": {"message": "content blocked", "code": "content_filter"}}
        http_error = __import__('requests.exceptions', fromlist=['HTTPError']).HTTPError(response=fake_resp)

        with patch.object(driver, '_request', side_effect=http_error):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertFalse(result['retry'])
        # 审核类错误应包含中文审核文案关键词
        self.assertTrue(
            any(kw in result['error'] for kw in ["违规", "敏感", "审核", "内容"]),
            f"error 应为审核友好文案，实际: {result['error']}"
        )

    def test_submit_http_429_rate_limit(self):
        """HTTP 429 限流：友好提示 + 自动重试"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='文生视频测试', image_path=None)

        sys.modules['utils.content_moderation_error'].is_content_moderation_user_message = MagicMock(return_value=False)

        fake_resp = MagicMock()
        fake_resp.status_code = 429
        fake_resp.json.return_value = {"error": {"message": "rate limited", "code": "RATE_LIMIT"}}
        http_error = __import__('requests.exceptions', fromlist=['HTTPError']).HTTPError(response=fake_resp)

        with patch.object(driver, '_request', side_effect=http_error):
            result = driver.submit_task(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertTrue(result['retry'])
        self.assertIn('限流', result['error'])

    def test_submit_network_error(self):
        """网络错误：返回 USER 错误且允许重试"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='文生视频测试', image_path=None)
        with patch.object(driver, '_request', side_effect=ConnectionError("refused")):
            result = driver.submit_task(ai_tool)
        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])


# ============================================================
# check_status 状态映射测试
# ============================================================
class TestCheckStatus(unittest.TestCase):
    """测试状态查询与映射"""

    def _driver(self):
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance20HuimengiV1Driver
        return _create_driver(Seedance20HuimengiV1Driver)

    def test_status_completed_returns_video_url(self):
        """completed：从 result.video_url 取地址"""
        driver = self._driver()
        video_url = "https://cdn.example.com/result.mp4"
        with patch.object(driver, '_request', return_value={
            "id": "a820e1b8-...",
            "model": "seedance-2.0",
            "status": "completed",
            "result": {
                "video_url": video_url,
                "duration": 5,
                "resolution": "720p",
                "ratio": "16:9"
            },
            "cost": 1.55,
            "created_at": "2026-04-24T10:00:00",
            "completed_at": "2026-04-24T10:01:20"
        }):
            result = driver.check_status("a820e1b8-...")
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], video_url)

    def test_status_failed_returns_error_message(self):
        """failed：返回 error_message 作为错误信息"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "id": "a820e1b8-...",
            "status": "failed",
            "error_message": "内容审核未通过",
            "cost": 0
        }):
            result = driver.check_status("a820e1b8-...")
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('内容审核', result['error'])

    def test_status_pending_running(self):
        """pending：映射为 RUNNING"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "id": "a820e1b8-...",
            "status": "pending"
        }):
            result = driver.check_status("a820e1b8-...")
        self.assertEqual(result['status'], 'RUNNING')

    def test_status_processing_running(self):
        """processing：映射为 RUNNING"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "id": "a820e1b8-...",
            "status": "processing"
        }):
            result = driver.check_status("a820e1b8-...")
        self.assertEqual(result['status'], 'RUNNING')

    def test_status_completed_but_missing_video_url(self):
        """completed 但缺 video_url：返回 SYSTEM FAILED"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "id": "a820e1b8-...",
            "status": "completed",
            "result": {"duration": 5}
        }):
            result = driver.check_status("a820e1b8-...")
        self.assertEqual(result['status'], 'FAILED')

    def test_status_error_message_url_sanitized(self):
        """error_message 误填为 URL 时应被过滤为默认失败信息"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "id": "a820e1b8-...",
            "status": "failed",
            "error_message": "https://cdn.example.com/misplaced.mp4",
            "cost": 0
        }):
            result = driver.check_status("a820e1b8-...")
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error'], '任务失败')

    def test_status_http_429_keeps_running(self):
        """查询时 429 限流：保持 RUNNING 等待下次轮询"""
        driver = self._driver()
        fake_resp = MagicMock()
        fake_resp.status_code = 429
        http_error = __import__('requests.exceptions', fromlist=['HTTPError']).HTTPError(response=fake_resp)
        with patch.object(driver, '_request', side_effect=http_error):
            result = driver.check_status("a820e1b8-...")
        self.assertEqual(result['status'], 'RUNNING')

    def test_status_network_error_keeps_running(self):
        """查询时网络错误：保持 RUNNING 等待重试"""
        driver = self._driver()
        with patch.object(driver, '_request', side_effect=ConnectionError("refused")):
            result = driver.check_status("a820e1b8-...")
        self.assertEqual(result['status'], 'RUNNING')


# ============================================================
# huimengi 自动处理人脸：遮盖素材恢复测试
# ============================================================
class TestResolvePathWithFaceMaskAutoFace(unittest.TestCase):
    """测试 huimengi 驱动在重试场景下从遮盖 step 恢复原始素材。

    huimengi 网关内置 human_review，始终应使用原始（未遮盖）素材。
    当任务从不支持自动处理人脸的实现方（如 volcengine）重试到 huimengi 时，
    遮盖预处理已执行，ai_tool.image_path 可能已被 apply_results 污染为网格图。
    _resolve_*_path_with_face_mask 负责从遗留 step 的 target 字段恢复原图。
    """

    def _driver(self):
        from task.visual_drivers.seedance_huimengi_v1_driver import Seedance20HuimengiV1Driver
        return _create_driver(Seedance20HuimengiV1Driver)

    def _make_step(self, step_type, target, result_url, status_completed=True):
        """构造 mock pipeline step"""
        from model.ai_tool_pipeline_steps import PipelineStepStatus
        step = MagicMock()
        step.step_type = step_type
        step.target = target
        step.result_url = result_url
        step.status = PipelineStepStatus.COMPLETED if status_completed else PipelineStepStatus.FAILED
        return step

    def test_image_path_unpolluted_returns_target(self):
        """image_path 等于 step.target（未被污染）：返回 target（原图）"""
        from model.ai_tool_pipeline_steps import PipelineStepType, PipelineStage
        driver = self._driver()
        ai_tool = _make_ai_tool()
        original = 'http://example.com/original.jpg'
        masked = 'http://example.com/grid.jpg'
        step = self._make_step(PipelineStepType.IMAGE_FACE_MASK, target=original, result_url=masked)
        with patch('task.visual_drivers.seedance_huimengi_v1_driver.PipelineStepModel') as mock_model:
            mock_model.get_by_ai_tool_and_stage.return_value = [step]
            result = driver._resolve_image_path_with_face_mask(ai_tool, original)
        self.assertEqual(result, original)

    def test_image_path_polluted_restores_target(self):
        """image_path 等于 step.result_url（已被 apply_results 污染为网格图）：恢复 target（原图）"""
        from model.ai_tool_pipeline_steps import PipelineStepType
        driver = self._driver()
        ai_tool = _make_ai_tool()
        original = 'http://example.com/original.jpg'
        masked = 'http://example.com/grid.jpg'
        step = self._make_step(PipelineStepType.IMAGE_FACE_MASK, target=original, result_url=masked)
        with patch('task.visual_drivers.seedance_huimengi_v1_driver.PipelineStepModel') as mock_model:
            mock_model.get_by_ai_tool_and_stage.return_value = [step]
            # 当前路径是网格图（被污染），应恢复为原图
            result = driver._resolve_image_path_with_face_mask(ai_tool, masked)
        self.assertEqual(result, original)

    def test_image_path_no_matching_step_unchanged(self):
        """无匹配的遮盖 step（首次命中 huimengi）：路径不变"""
        driver = self._driver()
        ai_tool = _make_ai_tool()
        original = 'http://example.com/original.jpg'
        with patch('task.visual_drivers.seedance_huimengi_v1_driver.PipelineStepModel') as mock_model:
            mock_model.get_by_ai_tool_and_stage.return_value = []
            result = driver._resolve_image_path_with_face_mask(ai_tool, original)
        self.assertEqual(result, original)

    def test_image_path_empty_unchanged(self):
        """空 image_path：直接返回"""
        driver = self._driver()
        ai_tool = _make_ai_tool()
        result = driver._resolve_image_path_with_face_mask(ai_tool, '')
        self.assertEqual(result, '')

    def test_video_path_polluted_restores_target(self):
        """video_path 等于 step.result_url（被污染）：恢复 target（原视频）"""
        from model.ai_tool_pipeline_steps import PipelineStepType
        driver = self._driver()
        ai_tool = _make_ai_tool()
        original = 'http://example.com/original.mp4'
        masked = 'http://example.com/grid.mp4'
        step = self._make_step(PipelineStepType.FACE_MASK, target=original, result_url=masked)
        with patch('task.visual_drivers.seedance_huimengi_v1_driver.PipelineStepModel') as mock_model:
            mock_model.get_by_ai_tool_and_stage.return_value = [step]
            result = driver._resolve_video_path_with_face_mask(ai_tool, masked)
        self.assertEqual(result, original)

    def test_video_path_unpolluted_returns_target(self):
        """video_path 等于 step.target（未被污染）：返回 target（原视频）"""
        from model.ai_tool_pipeline_steps import PipelineStepType
        driver = self._driver()
        ai_tool = _make_ai_tool()
        original = 'http://example.com/original.mp4'
        masked = 'http://example.com/grid.mp4'
        step = self._make_step(PipelineStepType.FACE_MASK, target=original, result_url=masked)
        with patch('task.visual_drivers.seedance_huimengi_v1_driver.PipelineStepModel') as mock_model:
            mock_model.get_by_ai_tool_and_stage.return_value = [step]
            result = driver._resolve_video_path_with_face_mask(ai_tool, original)
        self.assertEqual(result, original)

    def test_video_path_empty_unchanged(self):
        """空 video_path：直接返回"""
        driver = self._driver()
        ai_tool = _make_ai_tool()
        result = driver._resolve_video_path_with_face_mask(ai_tool, '')
        self.assertEqual(result, '')


if __name__ == '__main__':
    unittest.main()
