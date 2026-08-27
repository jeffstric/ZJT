"""
Seedance kkidc 网关驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

测试覆盖：
- 4 个子类初始化（1.5 Pro / 2.0 Fast / 2.0 / 2.0 Mini）
- build_create_request 四种模式：
    * 文生视频（纯文本，payload 顶层无 image）
    * 首帧图生视频（payload 顶层 image）
    * 首尾帧图生视频（metadata 内嵌 first_frame_image/last_frame_image）
    * 多参考图模式（metadata.reference_images）
- 响应校验（submit_response / status_response）
- submit_task：成功提取 task_id、HTTPError 400 内容审核、HTTPError 429 限流重试
- check_status：SUCCESS 取 video_url、FAILURE 取 fail_reason、QUEUED/IN_PROGRESS→RUNNING、
                内层小写状态回退、expired→FAILED、fail_reason 误填 URL 的容错
- 配置默认值与别名
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
        drv_mod = sys.modules.get('task.visual_drivers.seedance_kkidc_v1_driver')
        if drv_mod is not None:
            drv_mod.requests = real_requests


def _create_driver(cls, api_key='test_kkidc_key'):
    """创建 kkidc 驱动实例（mock 所有外部依赖）"""
    _ensure_real_requests()
    with patch('task.visual_drivers.seedance_kkidc_v1_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.seedance_kkidc_v1_driver.get_config', return_value={}):

        def side_effect(*keys, default=None):
            key_map = {
                ('kkidc', 'api_key'): api_key,
                ('kkidc', 'base_url'): 'https://ai-api.kkidc.com/v1',
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
    patcher = _patch('task.visual_drivers.seedance_kkidc_v1_driver.PipelineStepModel')
    mock_model = patcher.start()
    mock_model.get_by_ai_tool_and_stage.return_value = []
    return patcher


# ============================================================
# 子类初始化测试
# ============================================================
class TestSeedanceKkidcDriverInit(unittest.TestCase):
    """测试 3 个子类初始化"""

    def test_20_fast_init(self):
        from task.visual_drivers.seedance_kkidc_v1_driver import Seedance20FastKkidcV1Driver
        driver = _create_driver(Seedance20FastKkidcV1Driver)
        self.assertEqual(driver.driver_type, 22)
        self.assertEqual(driver._model, 'seed-2-fast')
        self.assertEqual(driver._base_url, 'https://ai-api.kkidc.com/v1')
        self.assertEqual(driver._api_key, 'test_kkidc_key')

    def test_20_init(self):
        from task.visual_drivers.seedance_kkidc_v1_driver import Seedance20KkidcV1Driver
        driver = _create_driver(Seedance20KkidcV1Driver)
        self.assertEqual(driver.driver_type, 23)
        self.assertEqual(driver._model, 'seed-2')

    def test_20_mini_init(self):
        from task.visual_drivers.seedance_kkidc_v1_driver import Seedance20MiniKkidcV1Driver
        driver = _create_driver(Seedance20MiniKkidcV1Driver)
        self.assertEqual(driver.driver_type, 31)
        self.assertEqual(driver._model, 'seed-2-mini')

    def test_base_url_trailing_slash_stripped(self):
        """base_url 尾部斜杠应被去除"""
        with patch('task.visual_drivers.seedance_kkidc_v1_driver.get_dynamic_config_value') as mock_config, \
             patch('task.visual_drivers.seedance_kkidc_v1_driver.get_config', return_value={}):

            def side_effect(*keys, default=None):
                key_map = {
                    ('kkidc', 'api_key'): 'k',
                    ('kkidc', 'base_url'): 'https://ai-api.kkidc.com/v1/',
                    ('timeout', 'request_timeout'): 30,
                    ('server', 'is_local'): False,
                    ('test_mode', 'enabled'): False,
                    ('test_mode', 'mock_videos'): {},
                }
                return key_map.get(keys, default)

            mock_config.side_effect = side_effect
            from task.visual_drivers.seedance_kkidc_v1_driver import Seedance20KkidcV1Driver
            driver = Seedance20KkidcV1Driver()
            self.assertEqual(driver._base_url, 'https://ai-api.kkidc.com/v1')


# ============================================================
# build_create_request 测试
# ============================================================
class TestBuildCreateRequest(unittest.TestCase):
    """测试请求构建（4 种模式）"""

    def setUp(self):
        _stub_image_upload_success()
        self._step_patcher = _stub_pipeline_steps_empty()

    def tearDown(self):
        self._step_patcher.stop()

    def _driver(self):
        from task.visual_drivers.seedance_kkidc_v1_driver import Seedance20KkidcV1Driver
        return _create_driver(Seedance20KkidcV1Driver)

    def test_text_to_video(self):
        """文生视频：顶层无 image，仅 prompt + metadata"""
        driver = self._driver()
        # 无图片、无音视频、extra_config 无 image_mode
        ai_tool = _make_ai_tool(
            prompt='一只猫在奔跑',
            image_path=None,
            extra_config={'generate_audio': True, 'watermark': False}
        )
        req = driver.build_create_request(ai_tool)

        self.assertEqual(req['method'], 'POST')
        self.assertEqual(req['url'], 'https://ai-api.kkidc.com/v1/video/generations')
        self.assertNotIn('image', req['json'])
        self.assertEqual(req['json']['prompt'], '一只猫在奔跑')
        self.assertEqual(req['json']['metadata']['generate_audio'], True)
        self.assertEqual(req['json']['metadata']['watermark'], False)
        self.assertEqual(req['json']['metadata']['duration'], 5)
        self.assertEqual(req['headers']['Authorization'], 'Bearer test_kkidc_key')

    def test_text_to_video_empty_prompt_rejected(self):
        """文生视频空 prompt 应返回错误"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='', image_path=None)
        result = driver.build_create_request(ai_tool)
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')

    def test_first_frame_only_uses_top_image(self):
        """仅首帧：顶层 image 字段，metadata 无 first_frame_image"""
        from task.visual_drivers import seedance_kkidc_v1_driver as drv_mod
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

        self.assertEqual(req['json']['image'], 'http://cdn.example.com/img.jpg')
        self.assertNotIn('first_frame_image', req['json']['metadata'])
        self.assertNotIn('last_frame_image', req['json']['metadata'])

    def test_first_last_frame_uses_metadata(self):
        """首尾帧：metadata 内嵌 first_frame_image / last_frame_image"""
        from task.visual_drivers import seedance_kkidc_v1_driver as drv_mod
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

        # 顶层不应有 image
        self.assertNotIn('image', req['json'])
        self.assertEqual(req['json']['metadata']['first_frame_image'], 'http://cdn.example.com/img.jpg')
        self.assertEqual(req['json']['metadata']['last_frame_image'], 'http://cdn.example.com/img.jpg')

    def test_multi_reference_images(self):
        """多参考图：metadata.reference_images 列表"""
        from task.visual_drivers import seedance_kkidc_v1_driver as drv_mod
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

        self.assertNotIn('image', req['json'])
        self.assertEqual(len(req['json']['metadata']['reference_images']), 2)
        self.assertNotIn('first_frame_image', req['json']['metadata'])

    def test_pure_audio_routes_to_multi_reference(self):
        """纯音频（无图无视频）：驱动兜底改判 multi_reference，metadata 含 reference_audios，
        不含 reference_images / first_frame_image（覆盖 CLI、storyboard 等非 server 入口）"""
        from task.visual_drivers import seedance_kkidc_v1_driver as drv_mod
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='纯音频测试', image_path=None, image_mode_declared=False,
                                audio_path='http://example.com/a.mp3')
        with patch.object(drv_mod, 'upload_media_to_cdn_sync',
                          return_value=(True, 'http://cdn.example.com/a.mp3', None)):
            req = driver.build_create_request(ai_tool)

        metadata = req['json']['metadata']
        self.assertEqual(metadata['reference_audios'], ['http://cdn.example.com/a.mp3'])
        self.assertNotIn('reference_images', metadata)
        self.assertNotIn('first_frame_image', metadata)


# ============================================================
# 响应校验测试
# ============================================================
class TestResponseValidation(unittest.TestCase):
    """测试 _validate_submit_response / _validate_status_response"""

    def _driver(self):
        from task.visual_drivers.seedance_kkidc_v1_driver import Seedance20KkidcV1Driver
        return _create_driver(Seedance20KkidcV1Driver)

    def test_submit_valid_three_section(self):
        """三段式响应：data.task_id 提取"""
        driver = self._driver()
        ok, err = driver._validate_submit_response({
            "code": "success", "message": "", "data": {"task_id": "cgt-xxx"}
        })
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_submit_valid_flat(self):
        """扁平式响应（真实线上结构）：顶层 task_id 提取"""
        driver = self._driver()
        ok, err = driver._validate_submit_response({
            "id": "task_UW6P6dfBaottRjZehPx7xYzhuoWNW87N",
            "task_id": "task_UW6P6dfBaottRjZehPx7xYzhuoWNW87N",
            "object": "video", "model": "seed-2-mini",
            "status": "queued", "progress": 0, "created_at": 1785170490
        })
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_submit_missing_task_id(self):
        """既无 data.task_id 也无顶层 task_id/id：报缺少 task_id"""
        driver = self._driver()
        ok, err = driver._validate_submit_response({"code": "success"})
        self.assertFalse(ok)
        self.assertIn("task_id", err)

    def test_extract_task_id_priority(self):
        """三段式优先于扁平式"""
        driver = self._driver()
        # 三段式 data.task_id 优先
        self.assertEqual(
            driver._extract_task_id({"data": {"task_id": "inner"}, "task_id": "outer"}),
            "inner"
        )
        # 无 data 时回退顶层
        self.assertEqual(driver._extract_task_id({"task_id": "only_top"}), "only_top")
        # 无 task_id 时回退 id
        self.assertEqual(driver._extract_task_id({"id": "fallback_id"}), "fallback_id")
        # 都没有
        self.assertIsNone(driver._extract_task_id({"foo": "bar"}))

    def test_submit_error_body(self):
        """非审核类错误：返回 API 错误 [code]: message"""
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

    def test_status_valid(self):
        driver = self._driver()
        ok, err = driver._validate_status_response({
            "code": "success",
            "data": {"task_id": "cgt-x", "status": "SUCCESS"}
        })
        self.assertTrue(ok)

    def test_status_missing_status(self):
        driver = self._driver()
        ok, err = driver._validate_status_response({
            "data": {"task_id": "cgt-x"}
        })
        self.assertFalse(ok)
        self.assertIn("status", err)


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
        from task.visual_drivers.seedance_kkidc_v1_driver import Seedance20KkidcV1Driver
        return _create_driver(Seedance20KkidcV1Driver)

    def test_submit_success_extracts_task_id(self):
        """成功响应：从 data.task_id 提取"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='文生视频测试', image_path=None)
        with patch.object(driver, '_request', return_value={
            "code": "success", "message": "",
            "data": {"task_id": "cgt-20260227150701-bwgfp"}
        }):
            result = driver.submit_task(ai_tool)

        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'cgt-20260227150701-bwgfp')

    def test_submit_success_flat_response(self):
        """扁平式成功响应（线上真实结构）：顶层 task_id 提取"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='女人站起来笑', image_path=None)
        # 复刻线上真实响应（无 data 包裹层）
        with patch.object(driver, '_request', return_value={
            "id": "task_UW6P6dfBaottRjZehPx7xYzhuoWNW87N",
            "task_id": "task_UW6P6dfBaottRjZehPx7xYzhuoWNW87N",
            "object": "video", "model": "seed-2-mini",
            "status": "queued", "progress": 0, "created_at": 1785170490
        }):
            result = driver.submit_task(ai_tool)

        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], "task_UW6P6dfBaottRjZehPx7xYzhuoWNW87N")

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

        fake_resp = MagicMock()
        fake_resp.status_code = 429
        fake_resp.json.return_value = {"error": {"message": "rate limited", "code": "RATE_LIMIT"}}
        http_error = __import__('requests.exceptions', fromlist=['HTTPError']).HTTPError(response=fake_resp)

        # patch 自动恢复；此前对 sys.modules 条目属性裸赋值不恢复，会污染后续测试
        with patch('utils.content_moderation_error.is_content_moderation_user_message',
                   return_value=False), \
             patch.object(driver, '_request', side_effect=http_error):
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
        from task.visual_drivers.seedance_kkidc_v1_driver import Seedance20KkidcV1Driver
        return _create_driver(Seedance20KkidcV1Driver)

    def test_status_success_returns_video_url(self):
        """SUCCESS：从 data.data.content.video_url 取地址"""
        driver = self._driver()
        video_url = "https://cdn.example.com/result.mp4"
        with patch.object(driver, '_request', return_value={
            "code": "success",
            "data": {
                "task_id": "cgt-x",
                "status": "SUCCESS",
                "data": {
                    "status": "succeeded",
                    "content": {"video_url": video_url}
                }
            }
        }):
            result = driver.check_status("cgt-x")
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], video_url)

    def test_status_success_flat_response(self):
        """扁平式成功响应（顶层 status + video_url）"""
        driver = self._driver()
        video_url = "https://cdn.example.com/flat.mp4"
        with patch.object(driver, '_request', return_value={
            "id": "task_x",
            "task_id": "task_x",
            "status": "succeeded",
            "video_url": video_url
        }):
            result = driver.check_status("task_x")
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], video_url)

    def test_status_failure_returns_fail_reason(self):
        """FAILURE：返回 fail_reason 作为错误信息"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "code": "success",
            "data": {
                "task_id": "cgt-x",
                "status": "FAILURE",
                "fail_reason": "内容审核未通过",
                "data": {"status": "failed"}
            }
        }):
            result = driver.check_status("cgt-x")
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('内容审核', result['error'])

    def test_status_queued_running(self):
        """QUEUED：映射为 RUNNING"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "code": "success",
            "data": {"task_id": "cgt-x", "status": "QUEUED"}
        }):
            result = driver.check_status("cgt-x")
        self.assertEqual(result['status'], 'RUNNING')

    def test_status_in_progress_running(self):
        """IN_PROGRESS：映射为 RUNNING"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "code": "success",
            "data": {"task_id": "cgt-x", "status": "IN_PROGRESS"}
        }):
            result = driver.check_status("cgt-x")
        self.assertEqual(result['status'], 'RUNNING')

    def test_status_inner_expired_maps_failed(self):
        """内层 status=expired：映射为 FAILED"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "code": "success",
            "data": {
                "task_id": "cgt-x",
                "status": "FAILURE",
                "fail_reason": "任务超时",
                "data": {"status": "expired"}
            }
        }):
            result = driver.check_status("cgt-x")
        self.assertEqual(result['status'], 'FAILED')

    def test_status_unknown_running(self):
        """UNKNOWN：保守映射为 RUNNING，避免误判失败"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "code": "success",
            "data": {"task_id": "cgt-x", "status": "UNKNOWN"}
        }):
            result = driver.check_status("cgt-x")
        self.assertEqual(result['status'], 'RUNNING')

    def test_status_success_but_missing_video_url(self):
        """SUCCESS 但缺 video_url：返回 SYSTEM FAILED"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "code": "success",
            "data": {
                "task_id": "cgt-x",
                "status": "SUCCESS",
                "data": {"status": "succeeded", "content": {}}
            }
        }):
            result = driver.check_status("cgt-x")
        self.assertEqual(result['status'], 'FAILED')

    def test_status_fail_reason_url_sanitized(self):
        """fail_reason 误填为 URL 时应被过滤为默认失败信息"""
        driver = self._driver()
        with patch.object(driver, '_request', return_value={
            "code": "success",
            "data": {
                "task_id": "cgt-x",
                "status": "FAILURE",
                "fail_reason": "https://cdn.example.com/misplaced.mp4",
                "data": {"status": "failed"}
            }
        }):
            result = driver.check_status("cgt-x")
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error'], '任务失败')

    def test_status_http_429_keeps_running(self):
        """查询时 429 限流：保持 RUNNING 等待下次轮询"""
        driver = self._driver()
        fake_resp = MagicMock()
        fake_resp.status_code = 429
        http_error = __import__('requests.exceptions', fromlist=['HTTPError']).HTTPError(response=fake_resp)
        with patch.object(driver, '_request', side_effect=http_error):
            result = driver.check_status("cgt-x")
        self.assertEqual(result['status'], 'RUNNING')

    def test_status_network_error_keeps_running(self):
        """查询时网络错误：保持 RUNNING 等待重试"""
        driver = self._driver()
        with patch.object(driver, '_request', side_effect=ConnectionError("refused")):
            result = driver.check_status("cgt-x")
        self.assertEqual(result['status'], 'RUNNING')


if __name__ == '__main__':
    unittest.main()
