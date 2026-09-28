# -*- coding: utf-8 -*-
"""
SeedanceTopenrouterV1 驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

覆盖：初始化（模型别名/配置覆盖）、任务路径、扩展状态（expired/cancelled）、
真人素材 asset:// 引用（human_review 门控与兜底）、素材上传失败降级为 SYSTEM 错误
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# 必须在导入会触发 model/database 的模块前，给 config_unit.yml 塞进一个最小配置缓存。
os.environ.setdefault("comfyui_env", "unit")
from config import config_util  # noqa: E402

config_util._config_cache["config_unit.yml"] = {
    "database": {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "",
        "database": "unit",
    },
    "server": {},
    "file_storage": {},
}

# Mock 外部依赖（在 import driver 之前；stub 随 with 块结束自动恢复，
# driver 模块导入后已缓存，继续持有 stub 模块的属性引用）
from tests.base.test_isolation import stub_modules  # noqa: E402

with stub_modules({
    'utils.sentry_util': MagicMock(),
    'utils.image_upload_utils': MagicMock(),
}):
    from task.visual_drivers import seedance_volcengine_v1_driver as _volc_drv_mod  # noqa: E402


def _passthrough_reference_audio_budget(paths, max_total_seconds, **kwargs):
    return [
        {"source": p, "path": p, "cleanup_path": None, "duration": None, "limit_seconds": 0.0}
        for p in paths
    ]


_volc_drv_mod.prepare_reference_audio_budget_sync = _passthrough_reference_audio_budget


def _create_driver(model_name='doubao-seedance-2-0-260128', driver_type=23,
                   impl_name='seedance_2_0_topenrouter_v1',
                   api_key='test_tpr_key', model_aliases=None, test_mode=False):
    """创建 SeedanceTopenrouterV1Driver 实例（mock 所有外部依赖）"""
    from task.visual_drivers.seedance_topenrouter_v1_driver import SeedanceTopenrouterV1Driver

    with patch('task.visual_drivers.seedance_topenrouter_v1_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.seedance_topenrouter_v1_driver.get_config', return_value={}):

        def side_effect(*keys, default=None):
            key_map = {
                ('topenrouter', 'api_key'): api_key,
                ('topenrouter', 'base_url'): '',
                ('topenrouter', 'model_aliases'): model_aliases if model_aliases is not None else {},
                ('timeout', 'request_timeout'): 30,
                ('server', 'is_local'): False,
                ('test_mode', 'enabled'): test_mode,
                ('test_mode', 'mock_videos'): {},
            }
            return key_map.get(keys, default)

        mock_config.side_effect = side_effect
        driver = SeedanceTopenrouterV1Driver(
            driver_type=driver_type, model_name=model_name, impl_name=impl_name
        )
        return driver


def _make_ai_tool(prompt='测试提示词', image_path='http://example.com/first.jpg',
                  extra_config=None, duration=5, ratio='9:16'):
    """创建模拟的 ai_tool 对象"""
    tool = MagicMock()
    tool.id = 1001
    tool.prompt = prompt
    tool.image_path = image_path
    tool.extra_config = extra_config
    tool.duration = duration
    tool.ratio = ratio
    tool.reference_images = None
    tool.audio_path = None
    tool.video_path = None
    return tool


class TestDriverInit(unittest.TestCase):
    """初始化：配置加载与模型名映射"""

    def test_default_init_and_model_alias(self):
        """默认模型别名：doubao-seedance-2-0-260128 → doubao-seedance-2.0"""
        driver = _create_driver()
        self.assertEqual(driver._model, 'doubao-seedance-2.0')
        self.assertEqual(driver._base_url, 'https://tp-api.chinadatapay.com:8000')
        self.assertEqual(driver._api_key, 'test_tpr_key')
        self.assertEqual(driver.driver_name, 'seedance_2_0_topenrouter_v1')

    def test_model_alias_json_config_override(self):
        """model_aliases 配置（JSON 字符串）覆盖默认映射"""
        driver = _create_driver(
            model_aliases='{"doubao-seedance-2-0-260128": "my-custom-model"}'
        )
        self.assertEqual(driver._model, 'my-custom-model')

    def test_model_alias_dict_config_override(self):
        driver = _create_driver(
            model_aliases={"doubao-seedance-2-0-260128": "dict-model"}
        )
        self.assertEqual(driver._model, 'dict-model')

    def test_unknown_model_passthrough(self):
        """未命中映射的模型名原样透传"""
        driver = _create_driver(model_name='doubao-seedance-9-9-999999')
        self.assertEqual(driver._model, 'doubao-seedance-9-9-999999')

    def test_25_model_alias_and_audio_limits(self):
        """2.5 子类：模型映射 + 音频限制与火山 2.5 一致"""
        from task.visual_drivers.seedance_topenrouter_v1_driver import Seedance25TopenrouterV1Driver
        with patch('task.visual_drivers.seedance_topenrouter_v1_driver.get_dynamic_config_value') as mock_config, \
             patch('task.visual_drivers.seedance_topenrouter_v1_driver.get_config', return_value={}):
            mock_config.side_effect = lambda *keys, default=None: {
                ('topenrouter', 'api_key'): 'k',
                ('test_mode', 'enabled'): False,
                ('test_mode', 'mock_videos'): {},
            }.get(keys, default)
            driver = Seedance25TopenrouterV1Driver()
        self.assertEqual(driver._model, 'doubao-seedance-2.5')
        self.assertEqual(driver.R2V_AUDIO_MAX_COUNT, 10)


class TestTaskPathAndStatus(unittest.TestCase):
    """任务路径与扩展状态"""

    def setUp(self):
        self.driver = _create_driver()

    def test_create_task_path(self):
        """提交路径为 /v1/video/tasks（非火山路径）"""
        result = self.driver.build_check_query('task-123')
        self.assertIn('/v1/video/tasks/task-123', result['url'])
        self.assertNotIn('contents/generations', result['url'])
        self.assertEqual(result['method'], 'GET')
        self.assertIn('Bearer test_tpr_key', result['headers']['Authorization'])

    def test_volcengine_base_path_unchanged(self):
        """火山基类路径不受影响（回归保护）"""
        from task.visual_drivers.seedance_volcengine_v1_driver import SeedanceVolcengineV1Driver
        self.assertEqual(
            SeedanceVolcengineV1Driver._create_task_path,
            '/api/v3/contents/generations/tasks',
        )

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_build_create_request_url(self, mock_compress):
        mock_compress.return_value = (True, 'https://cdn.example.com/first.jpg', None)
        ai_tool = _make_ai_tool(extra_config={'image_mode': 'first_last_frame'})
        result = self.driver.build_create_request(ai_tool)
        self.assertIn('/v1/video/tasks', result['url'])
        self.assertEqual(result['json']['model'], 'doubao-seedance-2.0')

    def test_validate_status_accepts_extended_statuses(self):
        """expired/cancelled 为合法状态"""
        for status in ('queued', 'running', 'succeeded', 'failed', 'expired', 'cancelled'):
            payload = {"id": "t1", "status": status}
            if status == 'succeeded':
                payload["content"] = {"video_url": "https://x/v.mp4"}
            is_valid, error = self.driver._validate_status_response(payload)
            self.assertTrue(is_valid, f"{status} 应合法: {error}")

    def test_validate_status_rejects_unknown(self):
        is_valid, error = self.driver._validate_status_response({"id": "t1", "status": "weird"})
        self.assertFalse(is_valid)

    def test_map_task_status(self):
        """expired/cancelled → failed，其余恒等"""
        self.assertEqual(self.driver._map_task_status('expired'), 'failed')
        self.assertEqual(self.driver._map_task_status('cancelled'), 'failed')
        self.assertEqual(self.driver._map_task_status('running'), 'running')
        self.assertEqual(self.driver._map_task_status('succeeded'), 'succeeded')

    def test_check_status_expired_maps_to_failed(self):
        """查询到 expired 状态：返回 FAILED（而非 RUNNING 死轮询）"""
        with patch.object(self.driver, '_request', return_value={
            "id": "t1", "status": "expired",
        }):
            result = self.driver.check_status('t1')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result.get('error_type'), 'USER')

    def test_check_status_succeeded(self):
        with patch.object(self.driver, '_request', return_value={
            "id": "t1", "status": "succeeded",
            "content": {"video_url": "https://cdn.example.com/v.mp4"},
        }):
            result = self.driver.check_status('t1')
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'https://cdn.example.com/v.mp4')


class TestAssetLibraryIntegration(unittest.TestCase):
    """真人素材 asset:// 引用（human_review 门控）"""

    def setUp(self):
        self.driver = _create_driver()
        # mock 素材客户端（驱动 __init__ 已构造真实客户端，测试中替换）
        self.asset_client = MagicMock()
        self.asset_client.create_asset.return_value = {
            "Id": "asset-001", "Status": "Processing"
        }
        self.asset_client.wait_asset_active.return_value = {
            "Id": "asset-001", "Status": "Active"
        }
        self.driver._asset_client = self.asset_client

    def _build(self, extra_config):
        ai_tool = _make_ai_tool(extra_config=extra_config)
        with patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync',
                   return_value=(True, 'https://cdn.example.com/first.jpg', None)):
            return self.driver.build_create_request(ai_tool)

    def test_human_review_true_uploads_asset(self):
        """human_review=true：素材上传素材库并替换为 asset://"""
        result = self._build({'image_mode': 'first_last_frame', 'human_review': True})
        self.assertTrue(result.get('success') is not False)
        self.asset_client.create_asset.assert_called_once_with(
            url='https://cdn.example.com/first.jpg', asset_type='Image'
        )
        self.asset_client.wait_asset_active.assert_called_once_with('asset-001')
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(len(image_items), 1)
        self.assertEqual(image_items[0]['image_url']['url'], 'asset://asset-001')

    def test_human_review_missing_enable_face_mask_fallback(self):
        """human_review 未声明但 enable_face_mask=true：兜底走素材库（跨实现方重试场景）"""
        result = self._build({'image_mode': 'first_last_frame', 'enable_face_mask': True})
        self.asset_client.create_asset.assert_called_once()
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(image_items[0]['image_url']['url'], 'asset://asset-001')

    def test_human_review_explicit_false_skips_asset(self):
        """human_review 显式 false：不走素材库，URL 原样"""
        result = self._build({'image_mode': 'first_last_frame', 'human_review': False})
        self.asset_client.create_asset.assert_not_called()
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(image_items[0]['image_url']['url'], 'https://cdn.example.com/first.jpg')

    def test_no_flags_skips_asset(self):
        """无任何标志：普通任务直传 CDN URL"""
        result = self._build({'image_mode': 'first_last_frame'})
        self.asset_client.create_asset.assert_not_called()
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(image_items[0]['image_url']['url'], 'https://cdn.example.com/first.jpg')

    def test_asset_upload_failure_returns_system_error(self):
        """素材上传失败：SYSTEM 错误且可重试（不静默降级直传）"""
        from utils.seedance_asset_client import SeedanceAssetError
        self.asset_client.create_asset.side_effect = SeedanceAssetError("素材接口网络异常")
        result = self._build({'image_mode': 'first_last_frame', 'human_review': True})
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'SYSTEM')
        self.assertTrue(result['retry'])

    def test_asset_url_not_reuploaded(self):
        """已是 asset:// 的引用不重复上传（幂等）"""
        ai_tool = _make_ai_tool(extra_config={'image_mode': 'first_last_frame', 'human_review': True})
        with patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync',
                   return_value=(True, 'asset://asset-exist', None)):
            result = self.driver.build_create_request(ai_tool)
        self.asset_client.create_asset.assert_not_called()
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(image_items[0]['image_url']['url'], 'asset://asset-exist')


class TestSubclassInstantiation(unittest.TestCase):
    """4 个子类实例化与注册名检查"""

    def test_subclasses(self):
        from task.visual_drivers.seedance_topenrouter_v1_driver import (
            Seedance20FastTopenrouterV1Driver,
            Seedance20TopenrouterV1Driver,
            Seedance20MiniTopenrouterV1Driver,
            Seedance25TopenrouterV1Driver,
        )
        with patch('task.visual_drivers.seedance_topenrouter_v1_driver.get_dynamic_config_value') as mock_config, \
             patch('task.visual_drivers.seedance_topenrouter_v1_driver.get_config', return_value={}):
            mock_config.side_effect = lambda *keys, default=None: {
                ('topenrouter', 'api_key'): 'k',
                ('test_mode', 'enabled'): False,
                ('test_mode', 'mock_videos'): {},
            }.get(keys, default)
            self.assertEqual(Seedance20FastTopenrouterV1Driver().driver_type, 22)
            self.assertEqual(Seedance20TopenrouterV1Driver().driver_type, 23)
            self.assertEqual(Seedance20MiniTopenrouterV1Driver().driver_type, 31)
            d25 = Seedance25TopenrouterV1Driver()
            self.assertEqual(d25.driver_type, 36)
            self.assertEqual(d25._model, 'doubao-seedance-2.5')


if __name__ == '__main__':
    unittest.main()
