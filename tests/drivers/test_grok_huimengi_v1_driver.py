"""
Grok huimengi 网关驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

测试覆盖：
- 初始化（driver_type=27、model=grok-video-channel、impl_name=grok_huimengi_v1）
- build_create_request：
    * 文生视频（无图片字段，ratio 缺省 9:16）
    * 首帧图生视频（params.image_url，尾帧忽略）
    * 多参考图模式（params.reference_images，7 张上限截断）
    * prompt 校验（空 / <5 字符 / >20000 截断）
    * duration 非法回退默认 10
    * 固定 resolution 720p、不透传 generate_audio/human_review、不含 webhook_url
- submit_task：成功提取 task_id、429 限流重试、网络错误重试
- check_status：completed/failed/pending/processing 状态映射（复用基类逻辑）
"""
import sys
import unittest
from unittest.mock import patch, MagicMock

# 防御：某些 driver_integration 测试会在模块级 `sys.modules['requests'] = MagicMock()`
# 全局污染 requests。基类 submit_task/check_status 用 `except requests.exceptions.HTTPError`
# 捕获异常，若 requests 被 mock 成 MagicMock，except 会抛 TypeError。
import importlib
_req_mod = sys.modules.get('requests')
if _req_mod is None or not hasattr(_req_mod, 'exceptions') or \
        not isinstance(getattr(_req_mod.exceptions, 'HTTPError', None), type):
    sys.modules.pop('requests', None)
    importlib.import_module('requests')

# Mock 外部依赖（必须在 import driver 之前）
# 注意：utils.content_moderation_error 不 mock，它只依赖标准库，需用真实逻辑校验
sys.modules['utils.sentry_util'] = MagicMock()
sys.modules['utils.image_upload_utils'] = MagicMock()


def _ensure_real_requests():
    """确保 requests 是真实模块（而非被其他测试 mock 成的 MagicMock）。

    与 seedance huimengi 测试相同的双层修复：还原 sys.modules，并强制重绑
    seedance 模块（submit_task/check_status 的定义处）的 requests 名字。
    """
    _req_mod = sys.modules.get('requests')
    http_error = getattr(getattr(_req_mod, 'exceptions', None), 'HTTPError', None)
    if not isinstance(http_error, type):
        sys.modules.pop('requests', None)
        sys.modules.pop('requests.exceptions', None)
        real_requests = importlib.import_module('requests')
        drv_mod = sys.modules.get('task.visual_drivers.seedance_huimengi_v1_driver')
        if drv_mod is not None:
            drv_mod.requests = real_requests


def _create_driver(api_key='test_huimengi_key'):
    """创建 Grok huimengi 驱动实例（mock 所有外部依赖）

    GrokHuimengiV1Driver 的配置加载全部位于基类 SeedanceHuimengiV1Driver.__init__，
    因此只需 patch seedance 模块的配置读取函数。
    """
    from task.visual_drivers.grok_huimengi_v1_driver import GrokHuimengiV1Driver
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
        driver = GrokHuimengiV1Driver()
        return driver


def _make_ai_tool(prompt='一只猫在海滩上漫步', image_path=None,
                  extra_config=None, duration=10, ratio='9:16',
                  reference_images=None):
    """创建模拟的 ai_tool 对象"""
    tool = MagicMock()
    tool.id = 3001
    tool.prompt = prompt
    tool.image_path = image_path
    tool.reference_images = reference_images
    tool.duration = duration
    tool.ratio = ratio
    tool.audio_path = None
    tool.video_path = None
    tool.extra_config = dict(extra_config or {})
    return tool


# ============================================================
# 初始化测试
# ============================================================
class TestGrokHuimengiDriverInit(unittest.TestCase):
    """测试 GrokHuimengiV1Driver 初始化"""

    def test_init(self):
        from config.unified_config import TaskTypeId, DriverImplementation
        driver = _create_driver()
        self.assertEqual(driver.driver_type, TaskTypeId.GROK_IMAGE_TO_VIDEO)
        self.assertEqual(TaskTypeId.GROK_IMAGE_TO_VIDEO, 27)
        self.assertEqual(driver._model, 'grok-video-channel')
        self.assertEqual(driver.driver_name, DriverImplementation.GROK_HUIMENGI_V1)
        self.assertEqual(driver.driver_name, 'grok_huimengi_v1')
        self.assertEqual(driver._base_url, 'https://api.huimengi.com')
        self.assertEqual(driver._api_key, 'test_huimengi_key')


# ============================================================
# build_create_request 测试
# ============================================================
class TestBuildCreateRequest(unittest.TestCase):
    """测试请求构建（文生 / 首帧 / 多参考 + 参数校验）"""

    def _driver(self):
        return _create_driver()

    def test_text_to_video(self):
        """文生视频：params 仅 prompt + 控制字段，无图片字段"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='一只猫在海滩上漫步', image_path=None)
        req = driver.build_create_request(ai_tool)

        self.assertEqual(req['method'], 'POST')
        self.assertEqual(req['url'], 'https://api.huimengi.com/api/v1/tasks')
        # huimengi 扁平结构：{ model, params }
        self.assertEqual(req['json']['model'], 'grok-video-channel')
        params = req['json']['params']
        self.assertEqual(params['prompt'], '一只猫在海滩上漫步')
        self.assertEqual(params['ratio'], '9:16')
        self.assertEqual(params['duration'], 10)
        self.assertEqual(params['resolution'], '720p')
        # 文生视频不应有图片字段
        self.assertNotIn('image_url', params)
        self.assertNotIn('reference_images', params)
        self.assertNotIn('first_frame_image', params)
        # 轮询模式，不下发 webhook
        self.assertNotIn('webhook_url', req['json'])
        self.assertEqual(req['headers']['Authorization'], 'Bearer test_huimengi_key')

    def test_ratio_from_extra_config(self):
        """ratio 优先取 extra_config，缺省回退 ai_tool.ratio / 9:16"""
        driver = self._driver()
        ai_tool = _make_ai_tool(image_path=None, ratio='16:9',
                                extra_config={'ratio': '1:1'})
        req = driver.build_create_request(ai_tool)
        self.assertEqual(req['json']['params']['ratio'], '1:1')

        ai_tool2 = _make_ai_tool(image_path=None, ratio=None)
        req2 = driver.build_create_request(ai_tool2)
        self.assertEqual(req2['json']['params']['ratio'], '9:16')

    def test_first_frame_uses_image_url(self):
        """首帧模式：params.image_url，无 first/last_frame_image"""
        driver = self._driver()
        ai_tool = _make_ai_tool(image_path='http://example.com/first.jpg',
                                extra_config={'image_mode': 'first_last_frame'})
        with patch.object(driver, 'get_all_images_by_mode', return_value={
            'mode': 'first_last_frame',
            'first_frame': 'http://example.com/first.jpg',
            'last_frame': None,
            'reference_images': []
        }), patch('task.visual_drivers.grok_huimengi_v1_driver.compress_and_upload_image_sync',
                  return_value=(True, 'http://cdn.example.com/img.jpg', None)) as mock_upload:
            req = driver.build_create_request(ai_tool)

        mock_upload.assert_called_once()
        params = req['json']['params']
        self.assertEqual(params['image_url'], 'http://cdn.example.com/img.jpg')
        self.assertNotIn('first_frame_image', params)
        self.assertNotIn('last_frame_image', params)
        self.assertNotIn('reference_images', params)

    def test_last_frame_ignored(self):
        """首尾帧输入：网关仅支持单张首帧，尾帧被忽略（仍是 image_url）"""
        driver = self._driver()
        ai_tool = _make_ai_tool(extra_config={'image_mode': 'first_last_frame'})
        with patch.object(driver, 'get_all_images_by_mode', return_value={
            'mode': 'first_last_frame',
            'first_frame': 'http://example.com/first.jpg',
            'last_frame': 'http://example.com/last.jpg',
            'reference_images': []
        }), patch('task.visual_drivers.grok_huimengi_v1_driver.compress_and_upload_image_sync',
                  return_value=(True, 'http://cdn.example.com/img.jpg', None)) as mock_upload:
            req = driver.build_create_request(ai_tool)

        # 尾帧被忽略：仅首帧上传一次
        self.assertEqual(mock_upload.call_count, 1)
        params = req['json']['params']
        self.assertEqual(params['image_url'], 'http://cdn.example.com/img.jpg')
        self.assertNotIn('last_frame_image', params)

    def test_multi_reference_images(self):
        """多参考图模式：params.reference_images 列表"""
        driver = self._driver()
        ai_tool = _make_ai_tool(extra_config={'image_mode': 'multi_reference'})
        with patch.object(driver, 'get_all_images_by_mode', return_value={
            'mode': 'multi_reference',
            'first_frame': None,
            'last_frame': None,
            'reference_images': ['http://example.com/a.jpg', 'http://example.com/b.jpg']
        }), patch('task.visual_drivers.grok_huimengi_v1_driver.compress_and_upload_image_sync',
                  side_effect=[(True, 'http://cdn.example.com/a.jpg', None),
                               (True, 'http://cdn.example.com/b.jpg', None)]):
            req = driver.build_create_request(ai_tool)

        params = req['json']['params']
        self.assertNotIn('image_url', params)
        self.assertEqual(params['reference_images'],
                         ['http://cdn.example.com/a.jpg', 'http://cdn.example.com/b.jpg'])

    def test_multi_reference_caps_at_seven(self):
        """多参考图超过 7 张：截取前 7 张"""
        driver = self._driver()
        ai_tool = _make_ai_tool(extra_config={'image_mode': 'multi_reference'})
        refs = [f'http://example.com/{i}.jpg' for i in range(9)]
        cdn_refs = [f'http://cdn.example.com/{i}.jpg' for i in range(9)]
        with patch.object(driver, 'get_all_images_by_mode', return_value={
            'mode': 'multi_reference',
            'first_frame': None,
            'last_frame': None,
            'reference_images': refs
        }), patch('task.visual_drivers.grok_huimengi_v1_driver.compress_and_upload_image_sync',
                  side_effect=[(True, url, None) for url in cdn_refs]):
            req = driver.build_create_request(ai_tool)

        self.assertEqual(len(req['json']['params']['reference_images']), 7)

    def test_multi_reference_all_failed_user_error(self):
        """参考图全部处理失败：返回 USER 错误，不发起请求"""
        driver = self._driver()
        ai_tool = _make_ai_tool(extra_config={'image_mode': 'multi_reference'})
        with patch.object(driver, 'get_all_images_by_mode', return_value={
            'mode': 'multi_reference',
            'first_frame': None,
            'last_frame': None,
            'reference_images': ['http://example.com/a.jpg']
        }), patch('task.visual_drivers.grok_huimengi_v1_driver.compress_and_upload_image_sync',
                  return_value=(False, None, '上传失败')):
            result = driver.build_create_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertFalse(result['retry'])

    def test_first_frame_upload_failed_user_error(self):
        """首帧处理失败：返回 USER 错误不重试"""
        driver = self._driver()
        ai_tool = _make_ai_tool(extra_config={'image_mode': 'first_last_frame'})
        with patch.object(driver, 'get_all_images_by_mode', return_value={
            'mode': 'first_last_frame',
            'first_frame': 'http://example.com/first.jpg',
            'last_frame': None,
            'reference_images': []
        }), patch('task.visual_drivers.grok_huimengi_v1_driver.compress_and_upload_image_sync',
                  return_value=(False, None, '图片损坏')):
            result = driver.build_create_request(ai_tool)

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertFalse(result['retry'])

    def test_prompt_empty_rejected(self):
        """空 prompt：USER 错误"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='   ', image_path=None)
        result = driver.build_create_request(ai_tool)
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')

    def test_prompt_too_short_rejected(self):
        """prompt 少于 5 字符：USER 错误并提示长度要求"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='猫', image_path=None)
        result = driver.build_create_request(ai_tool)
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertIn('5', result['error'])

    def test_prompt_truncated_to_max(self):
        """prompt 超过 20000 字符：截断"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='猫' * 20005, image_path=None)
        req = driver.build_create_request(ai_tool)
        self.assertEqual(len(req['json']['params']['prompt']), 20000)

    def test_duration_invalid_fallback(self):
        """duration 非法档位：回退默认 10；None 也回退默认"""
        driver = self._driver()
        ai_tool = _make_ai_tool(image_path=None, duration=8)
        req = driver.build_create_request(ai_tool)
        self.assertEqual(req['json']['params']['duration'], 10)

        ai_tool2 = _make_ai_tool(image_path=None, duration=None)
        req2 = driver.build_create_request(ai_tool2)
        self.assertEqual(req2['json']['params']['duration'], 10)

    def test_duration_valid_passthrough(self):
        """duration 合法档位 6/10/15 透传"""
        driver = self._driver()
        for duration in (6, 10, 15):
            ai_tool = _make_ai_tool(image_path=None, duration=duration)
            req = driver.build_create_request(ai_tool)
            self.assertEqual(req['json']['params']['duration'], duration)

    def test_seedance_only_fields_not_passed(self):
        """grok 网关不支持 generate_audio / human_review / 参考音视频，不透传"""
        driver = self._driver()
        ai_tool = _make_ai_tool(
            image_path=None,
            extra_config={'generate_audio': True, 'human_review': True},
            reference_images=None
        )
        req = driver.build_create_request(ai_tool)
        params = req['json']['params']
        self.assertNotIn('generate_audio', params)
        self.assertNotIn('human_review', params)
        self.assertNotIn('reference_videos', params)
        self.assertNotIn('reference_audios', params)


# ============================================================
# submit_task 流程测试
# ============================================================
class TestSubmitTask(unittest.TestCase):
    """测试提交任务流程（基类通用逻辑 + grok 请求体）"""

    def _driver(self):
        return _create_driver()

    def test_submit_success_extracts_task_id(self):
        """成功响应：从顶层 task_id 提取，model 为 grok-video-channel"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='一只猫在海滩上漫步', image_path=None)
        with patch.object(driver, '_request', return_value={
            "task_id": "a820e1b8-fb15-4ec9-a13c-bdd1d4eb6679",
            "status": "pending"
        }) as mock_request:
            result = driver.submit_task(ai_tool)

        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], 'a820e1b8-fb15-4ec9-a13c-bdd1d4eb6679')
        # 请求体为扁平 { model, params } 结构
        call_json = mock_request.call_args[1]['json']
        self.assertEqual(call_json['model'], 'grok-video-channel')
        self.assertIn('params', call_json)

    def test_submit_http_429_rate_limit(self):
        """HTTP 429 限流：友好提示 + 自动重试"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='一只猫在海滩上漫步', image_path=None)

        fake_resp = MagicMock()
        fake_resp.status_code = 429
        fake_resp.json.return_value = {"error": {"message": "rate limited", "code": "RATE_LIMIT"}}
        http_error = __import__('requests.exceptions', fromlist=['HTTPError']).HTTPError(response=fake_resp)

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
        ai_tool = _make_ai_tool(prompt='一只猫在海滩上漫步', image_path=None)
        with patch.object(driver, '_request', side_effect=ConnectionError("refused")):
            result = driver.submit_task(ai_tool)
        self.assertFalse(result['success'])
        self.assertTrue(result['retry'])

    def test_submit_build_error_passthrough(self):
        """build_create_request 返回 USER 错误（如 prompt 过短）时直接透传，不发起请求"""
        driver = self._driver()
        ai_tool = _make_ai_tool(prompt='猫', image_path=None)
        with patch.object(driver, '_request') as mock_request:
            result = driver.submit_task(ai_tool)
        mock_request.assert_not_called()
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')


# ============================================================
# check_status 状态映射测试
# ============================================================
class TestCheckStatus(unittest.TestCase):
    """测试状态查询与映射（复用基类 huimengi 网关逻辑）"""

    def _driver(self):
        return _create_driver()

    def test_status_completed_returns_video_url(self):
        """completed：从 result.video_url 取地址"""
        driver = self._driver()
        video_url = "https://cdn.example.com/result.mp4"
        with patch.object(driver, '_request', return_value={
            "id": "a820e1b8-...",
            "model": "grok-video-channel",
            "status": "completed",
            "result": {"video_url": video_url, "duration": 6, "resolution": "720p"},
            "cost": 0.3,
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

    def test_status_pending_and_processing_running(self):
        """pending / processing：映射为 RUNNING"""
        driver = self._driver()
        for raw in ("pending", "processing"):
            with patch.object(driver, '_request', return_value={
                "id": "a820e1b8-...",
                "status": raw
            }):
                result = driver.check_status("a820e1b8-...")
            self.assertEqual(result['status'], 'RUNNING')

    def test_status_http_429_keeps_running(self):
        """查询时 429 限流：保持 RUNNING 等待下次轮询"""
        driver = self._driver()
        fake_resp = MagicMock()
        fake_resp.status_code = 429
        http_error = __import__('requests.exceptions', fromlist=['HTTPError']).HTTPError(response=fake_resp)
        with patch.object(driver, '_request', side_effect=http_error):
            result = driver.check_status("a820e1b8-...")
        self.assertEqual(result['status'], 'RUNNING')


if __name__ == '__main__':
    unittest.main()
