# -*- coding: utf-8 -*-
"""
SeedanceTopenrouterV1 驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

覆盖：初始化（模型别名/配置覆盖）、任务路径、扩展状态（expired/cancelled）、
真人素材三模式分派（human_asset_mode × enable_face_mask 勾选，human_review
残留重算）、素材上传失败降级为 SYSTEM 错误、终态素材回收
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
        """默认无别名：网关原生支持火山原名（/v1/models 实测），模型名原样透传"""
        driver = _create_driver()
        self.assertEqual(driver._model, 'doubao-seedance-2-0-260128')
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
        self.assertEqual(driver._model, 'doubao-seedance-2-5-260628')
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
        self.assertEqual(result['json']['model'], 'doubao-seedance-2-0-260128')

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
    """真人素材三模式分派（human_asset_mode + enable_face_mask 勾选）"""

    def setUp(self):
        self.driver = _create_driver()
        # mock 素材客户端（懒建缓存实例，测试中替换）
        self.asset_client = MagicMock()
        self.asset_client.create_asset.return_value = {
            "Id": "asset-001", "Status": "Processing"
        }
        self.asset_client.wait_asset_active.return_value = {
            "Id": "asset-001", "Status": "Active"
        }
        self.driver._asset_client_instance = self.asset_client
        # 默认 asset_library 模式（等价生产 topenrouter 默认；单测配置缓存无该键）
        patcher = patch.object(self.driver, '_resolve_human_asset_mode',
                               return_value='asset_library')
        patcher.start()
        self.addCleanup(patcher.stop)

    def _build(self, extra_config):
        ai_tool = _make_ai_tool(extra_config=extra_config)
        with patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync',
                   return_value=(True, 'https://cdn.example.com/first.jpg', None)):
            return self.driver.build_create_request(ai_tool)

    def test_enable_face_mask_uploads_asset(self):
        """asset_library 模式 + 勾选处理人脸：素材上传素材库并替换为 asset://"""
        result = self._build({'image_mode': 'first_last_frame', 'enable_face_mask': True})
        self.assertTrue(result.get('success') is not False)
        self.asset_client.create_asset.assert_called_once_with(
            url='https://cdn.example.com/first.jpg', asset_type='Image'
        )
        self.asset_client.wait_asset_active.assert_called_once_with('asset-001')
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(len(image_items), 1)
        self.assertEqual(image_items[0]['image_url']['url'], 'asset://asset-001')

    def test_stale_human_review_without_flag_skips_asset(self):
        """残留的 human_review=true（跨实现方重试 extra_config 固化）不再生效：
        未勾选 enable_face_mask 时不走素材库——每次提交按当前实现方模式现场重算"""
        result = self._build({'image_mode': 'first_last_frame', 'human_review': True})
        self.asset_client.create_asset.assert_not_called()
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(image_items[0]['image_url']['url'], 'https://cdn.example.com/first.jpg')

    def test_stale_human_review_false_with_flag_uploads_asset(self):
        """残留 human_review=false 同样被无视：勾选 enable_face_mask 即按模式处理"""
        result = self._build({'image_mode': 'first_last_frame',
                              'human_review': False, 'enable_face_mask': True})
        self.asset_client.create_asset.assert_called_once()
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(image_items[0]['image_url']['url'], 'asset://asset-001')

    def test_no_flags_skips_asset(self):
        """无任何标志：普通任务直传 CDN URL"""
        result = self._build({'image_mode': 'first_last_frame'})
        self.asset_client.create_asset.assert_not_called()
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(image_items[0]['image_url']['url'], 'https://cdn.example.com/first.jpg')

    def test_face_mask_mode_skips_asset(self):
        """face_mask 模式（本地遮盖）：驱动不介入，URL 原样"""
        with patch.object(self.driver, '_resolve_human_asset_mode', return_value='face_mask'):
            result = self._build({'image_mode': 'first_last_frame', 'enable_face_mask': True})
        self.asset_client.create_asset.assert_not_called()
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(image_items[0]['image_url']['url'], 'https://cdn.example.com/first.jpg')

    def test_param_pass_mode_injects_human_review(self):
        """param_pass 模式 + 勾选：json 顶层注入 human_review=true，不动素材"""
        with patch.object(self.driver, '_resolve_human_asset_mode', return_value='param_pass'):
            result = self._build({'image_mode': 'first_last_frame', 'enable_face_mask': True})
        self.asset_client.create_asset.assert_not_called()
        self.assertIs(result['json'].get('human_review'), True)

    def test_asset_upload_failure_returns_system_error(self):
        """素材上传失败：SYSTEM 错误且可重试（不静默降级直传）"""
        from utils.seedance_asset_client import SeedanceAssetError
        self.asset_client.create_asset.side_effect = SeedanceAssetError("素材接口网络异常")
        result = self._build({'image_mode': 'first_last_frame', 'enable_face_mask': True})
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'SYSTEM')
        self.assertTrue(result['retry'])

    def test_asset_url_not_reuploaded(self):
        """已是 asset:// 的引用不重复上传（幂等）"""
        ai_tool = _make_ai_tool(extra_config={'image_mode': 'first_last_frame', 'enable_face_mask': True})
        with patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync',
                   return_value=(True, 'asset://asset-exist', None)):
            result = self.driver.build_create_request(ai_tool)
        self.asset_client.create_asset.assert_not_called()
        image_items = [c for c in result['json']['content'] if c['type'] == 'image_url']
        self.assertEqual(image_items[0]['image_url']['url'], 'asset://asset-exist')

    def test_terminal_status_cleans_created_assets(self):
        """任务到达终态后回收本次创建的素材（生命周期不堆积）"""
        self.driver._record_created_asset('asset-001')
        # 非终态不清理
        self.driver._cleanup_assets_if_terminal('RUNNING')
        self.asset_client.delete_asset.assert_not_called()
        # 各家终态形态（volcengine 小写 / huimengi 大写）均触发清理
        for status in ('succeeded', 'failed', 'SUCCESS', 'FAILED', 'COMPLETED'):
            self.driver._record_created_asset(f'asset-{status}')
            self.driver._cleanup_assets_if_terminal(status)
        self.assertEqual(self.asset_client.delete_asset.call_count, 6)
        # 清理幂等：无待清理素材时再调不报错不重复
        self.driver._cleanup_assets_if_terminal('SUCCESS')
        self.assertEqual(self.asset_client.delete_asset.call_count, 6)


class TestHumanAssetModeResolution(unittest.TestCase):
    """模式解析：read_human_asset_mode 回落语义与工厂 resolver"""

    def test_no_group_defaults_to_face_mask(self):
        """未声明组（grok/kkidc 等未接入者）恒为 face_mask"""
        from task.visual_drivers.seedance_human_asset_mixin import read_human_asset_mode
        self.assertEqual(read_human_asset_mode(None), 'face_mask')
        self.assertEqual(read_human_asset_mode(''), 'face_mask')

    def test_unconfigured_group_defaults_to_face_mask(self):
        """组未配置 human_asset_mode：回落 face_mask（kkidc 等新网关默认本地遮盖）"""
        import task.visual_drivers.seedance_human_asset_mixin as mixin_mod
        with patch.object(mixin_mod, 'get_dynamic_config_value',
                          side_effect=lambda *keys, default=None: default):
            from task.visual_drivers.seedance_human_asset_mixin import read_human_asset_mode
            self.assertEqual(read_human_asset_mode('kkidc'), 'face_mask')

    def test_invalid_mode_falls_back_to_face_mask(self):
        """非法配置值：警告并回落 face_mask"""
        import task.visual_drivers.seedance_human_asset_mixin as mixin_mod
        with patch.object(mixin_mod, 'get_dynamic_config_value',
                          return_value='yolo_mode'):
            from task.visual_drivers.seedance_human_asset_mixin import read_human_asset_mode
            self.assertEqual(read_human_asset_mode('huimengi'), 'face_mask')

    def test_valid_modes_pass_through(self):
        """三种合法值原样返回"""
        import task.visual_drivers.seedance_human_asset_mixin as mixin_mod
        from task.visual_drivers.seedance_human_asset_mixin import read_human_asset_mode
        for mode in ('face_mask', 'asset_library', 'param_pass'):
            with patch.object(mixin_mod, 'get_dynamic_config_value', return_value=mode):
                self.assertEqual(read_human_asset_mode('huimengi'), mode)

    def test_factory_resolver_by_impl_name(self):
        """工厂 resolver：按实现方名查驱动类声明的组（grok 覆盖回 None 恒 face_mask）"""
        from task.visual_drivers.driver_factory import VideoDriverFactory, register_all_drivers
        register_all_drivers()
        from task.visual_drivers.seedance_topenrouter_v1_driver import SeedanceTopenrouterV1Driver
        from task.visual_drivers.seedance_huimengi_v1_driver import SeedanceHuimengiV1Driver
        from task.visual_drivers.grok_huimengi_v1_driver import GrokHuimengiV1Driver
        from task.visual_drivers.seedance_volcengine_v1_driver import SeedanceVolcengineV1Driver
        from task.visual_drivers.seedance_volcengine_oversea_v1_driver import SeedanceVolcengineOverseaV1Driver

        self.assertEqual(SeedanceTopenrouterV1Driver._human_asset_config_group, 'topenrouter')
        self.assertEqual(SeedanceHuimengiV1Driver._human_asset_config_group, 'huimengi')
        self.assertIsNone(GrokHuimengiV1Driver._human_asset_config_group)
        # 火山直连已挂 volcengine 组：按组配置三模式分派（默认仍 face_mask）
        self.assertEqual(SeedanceVolcengineV1Driver._human_asset_config_group, 'volcengine')
        # 海外版显式不继承国内组（账号/区域隔离，素材库直连未接入海外版）
        self.assertIsNone(SeedanceVolcengineOverseaV1Driver._human_asset_config_group)
        # TopenRouter 模式写死官方真人库透传：不读组配置（配置键已移除）
        self.assertEqual(SeedanceTopenrouterV1Driver._human_asset_mode_fixed, 'asset_library')

        import task.visual_drivers.seedance_human_asset_mixin as mixin_mod
        with patch.object(mixin_mod, 'get_dynamic_config_value',
                          side_effect=lambda *keys, default=None: 'param_pass'):
            self.assertEqual(
                VideoDriverFactory.resolve_human_asset_mode('seedance_2_0_huimengi_v1'),
                'param_pass',
            )
            # 火山直连：声明组后同样按配置分派
            self.assertEqual(
                VideoDriverFactory.resolve_human_asset_mode('seedance_2_0_fast_volcengine_v1'),
                'param_pass',
            )
            # TopenRouter：写死模式，配置 mock 成 param_pass 仍返回 asset_library
            self.assertEqual(
                VideoDriverFactory.resolve_human_asset_mode('seedance_2_0_fast_topenrouter_v1'),
                'asset_library',
            )
            # grok 未挂组：不读配置，恒 face_mask
            self.assertEqual(
                VideoDriverFactory.resolve_human_asset_mode('grok_huimengi_v1'),
                'face_mask',
            )
        self.assertEqual(
            VideoDriverFactory.resolve_human_asset_mode('nonexistent_impl'),
            'face_mask',
        )


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
            self.assertEqual(d25._model, 'doubao-seedance-2-5-260628')


if __name__ == '__main__':
    unittest.main()
