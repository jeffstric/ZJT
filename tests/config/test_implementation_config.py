"""
实现方配置相关单元测试
测试 UnifiedConfigRegistry 的实现方管理功能和 ImplementationConfig 类
"""
import unittest
from unittest.mock import patch, MagicMock


class TestUnifiedConfigRegistryImplementations(unittest.TestCase):
    """UnifiedConfigRegistry 实现方管理功能测试"""

    def setUp(self):
        """测试前准备"""
        # 导入模块
        from config.unified_config import UnifiedConfigRegistry, ALL_IMPLEMENTATIONS, init_unified_config

        # 重新初始化配置（确保干净状态）
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

        # 初始化基础配置
        init_unified_config()

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def test_get_implementation_existing(self):
        """测试获取已存在的实现方配置"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('sora2_duomi_v1')
        self.assertIsNotNone(impl)
        self.assertEqual(impl.name, 'sora2_duomi_v1')
        self.assertEqual(impl.display_name, '多米')

    def test_get_implementation_non_existing(self):
        """测试获取不存在的实现方配置"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('nonexistent_impl')
        self.assertIsNone(impl)

    def test_get_all_implementations(self):
        """测试获取所有实现方配置"""
        from config.unified_config import UnifiedConfigRegistry

        all_impls = UnifiedConfigRegistry.get_all_implementations()
        self.assertIsInstance(all_impls, dict)
        self.assertGreater(len(all_impls), 0)

        # 验证包含已知的实现方
        self.assertIn('sora2_duomi_v1', all_impls)
        self.assertIn('gemini_duomi_v1', all_impls)
        self.assertIn('seedream5_volcengine_v1', all_impls)

    def test_get_enabled_implementations(self):
        """测试获取所有启用的实现方配置"""
        from config.unified_config import UnifiedConfigRegistry

        enabled_impls = UnifiedConfigRegistry.get_enabled_implementations()
        self.assertIsInstance(enabled_impls, list)
        self.assertGreater(len(enabled_impls), 0)

        # 验证所有返回的都是启用状态
        for impl in enabled_impls:
            self.assertTrue(impl.enabled or impl.is_enabled())

    def test_implementation_register_and_get(self):
        """测试注册和获取实现方"""
        from config.unified_config import UnifiedConfigRegistry, ImplementationConfig

        # 创建一个新实现方配置
        new_impl = ImplementationConfig(
            name='test_impl_v1',
            display_name='测试实现方',
            driver_class='TestDriver',
            default_computing_power=5,
            enabled=True,
            description='测试用实现方'
        )

        # 注册
        UnifiedConfigRegistry.register_implementation(new_impl)

        # 获取并验证
        retrieved = UnifiedConfigRegistry.get_implementation('test_impl_v1')
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, 'test_impl_v1')
        self.assertEqual(retrieved.display_name, '测试实现方')
        self.assertEqual(retrieved.default_computing_power, 5)

    def test_register_all_implementations(self):
        """测试批量注册实现方"""
        from config.unified_config import UnifiedConfigRegistry, ImplementationConfig

        # 创建多个测试实现方
        test_impls = [
            ImplementationConfig(
                name='test_impl_batch_1',
                display_name='批量测试1',
                driver_class='TestDriver1',
                default_computing_power=1,
                enabled=True
            ),
            ImplementationConfig(
                name='test_impl_batch_2',
                display_name='批量测试2',
                driver_class='TestDriver2',
                default_computing_power=2,
                enabled=True
            )
        ]

        # 批量注册
        UnifiedConfigRegistry.register_all_implementations(test_impls)

        # 验证注册成功
        self.assertIsNotNone(UnifiedConfigRegistry.get_implementation('test_impl_batch_1'))
        self.assertIsNotNone(UnifiedConfigRegistry.get_implementation('test_impl_batch_2'))


class TestImplementationConfig(unittest.TestCase):
    """ImplementationConfig 类测试"""

    def setUp(self):
        """测试前准备"""
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry._implementations.clear()
        UnifiedConfigRegistry.register_all_implementations([
            ImplementationConfig(
                name='test_impl',
                display_name='测试实现方',
                driver_class='TestDriver',
                default_computing_power=5,
                enabled=True,
                description='测试用实现方'
            ),
            ImplementationConfig(
                name='test_impl_dict_power',
                display_name='按时长算力',
                driver_class='TestDriver2',
                default_computing_power={5: 10, 10: 20},
                enabled=True
            ),
            ImplementationConfig(
                name='test_impl_disabled',
                display_name='已禁用',
                driver_class='TestDriver3',
                default_computing_power=3,
                enabled=False
            )
        ])

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry._implementations.clear()

    def test_get_computing_power_simple(self):
        """测试固定算力获取"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('test_impl')
        self.assertIsNotNone(impl)
        self.assertEqual(impl.get_computing_power(), 5)

    def test_get_computing_power_by_duration(self):
        """测试按时长算力获取"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('test_impl_dict_power')
        self.assertIsNotNone(impl)

        # 指定时长
        self.assertEqual(impl.get_computing_power(duration=5), 10)
        self.assertEqual(impl.get_computing_power(duration=10), 20)

        # 不指定时长或时长不在映射中，返回第一个值
        self.assertEqual(impl.get_computing_power(duration=7), 10)  # 默认返回第一个
        self.assertEqual(impl.get_computing_power(), 10)  # 无时长参数

    def test_video_resolution_fields_default_to_empty_values(self):
        """实现方默认不支持视频分辨率选择"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('test_impl')

        self.assertEqual(impl.supported_video_resolutions, [])
        self.assertEqual(impl.default_video_resolution, '')

    def test_video_resolution_fields_can_be_configured(self):
        """实现方可配置结构化视频分辨率选项"""
        from config.unified_config import ImplementationConfig

        impl = ImplementationConfig(
            name='test_video_resolution_impl',
            display_name='测试分辨率实现',
            driver_class='TestDriver',
            supported_video_resolutions=[
                {'value': '720P', 'label': '720P'},
                {'value': '1080P', 'label': '1080P'},
            ],
            default_video_resolution='720P',
        )

        self.assertEqual(impl.default_video_resolution, '720P')
        self.assertEqual(impl.supported_video_resolutions[1]['value'], '1080P')

    def test_seedance_2_0_implementations_expose_video_resolutions(self):
        """Seedance 2.0 系列实现方应暴露可选视频分辨率"""
        from config.unified_config import UnifiedConfigRegistry, init_unified_config

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()
        init_unified_config()

        expected = {
            'seedance_2_0_fast_volcengine_v1': ['480P', '720P'],
            'seedance_2_0_fast_volcengine_oversea_v1': ['480P', '720P'],
            'seedance_2_0_mini_volcengine_v1': ['480P', '720P'],
            'seedance_2_0_mini_volcengine_oversea_v1': ['480P', '720P'],
            'seedance_2_0_volcengine_v1': ['480P', '720P', '1080P', '4K'],
            'seedance_2_0_volcengine_oversea_v1': ['480P', '720P', '1080P', '4K'],
        }

        for impl_name, expected_values in expected.items():
            impl = UnifiedConfigRegistry.get_implementation(impl_name)
            with self.subTest(impl_name=impl_name):
                self.assertIsNotNone(impl)
                self.assertEqual(impl.default_video_resolution, '720P')
                self.assertEqual(
                    [item['value'] for item in impl.supported_video_resolutions],
                    expected_values,
                )

    def test_is_enabled_default(self):
        """测试默认启用状态"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('test_impl')
        self.assertTrue(impl.is_enabled())

    def test_is_enabled_disabled(self):
        """测试禁用状态"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('test_impl_disabled')
        self.assertFalse(impl.is_enabled())

    def test_get_display_name(self):
        """测试获取显示名称"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('test_impl')
        self.assertEqual(impl.get_display_name(), '测试实现方')

    def test_to_dict(self):
        """测试转换为字典"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('test_impl')
        self.assertIsNotNone(impl)

        d = impl.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d['name'], 'test_impl')
        self.assertEqual(d['display_name'], '测试实现方')
        self.assertEqual(d['default_computing_power'], 5)
        self.assertTrue(d['enabled'])

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_get_computing_power_with_driver_key_db_override(self, mock_model):
        """传入 driver_key 时应使用数据库配置的算力覆盖值"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('test_impl_dict_power')
        mock_model.get_all_powers_for_implementation.return_value = {5: 99, 10: 199}

        result = impl.get_computing_power(duration=5, driver_key='TEST_DRIVER')

        self.assertEqual(result, 99)
        mock_model.get_all_powers_for_implementation.assert_called_once_with(
            'test_impl_dict_power', 'TEST_DRIVER'
        )

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_get_computing_power_with_driver_key_and_duration(self, mock_model):
        """数据库有对应时长的配置时应正确返回"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('test_impl_dict_power')
        mock_model.get_all_powers_for_implementation.return_value = {5: 88}

        result = impl.get_computing_power(duration=5, driver_key='TEST_DRIVER')

        self.assertEqual(result, 88)

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_get_computing_power_without_driver_key_uses_legacy_path(self, mock_model):
        """未传 driver_key 时应走旧的 get_power 路径（向后兼容）"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('test_impl')
        mock_model.get_power.return_value = 42

        result = impl.get_computing_power()

        self.assertEqual(result, 42)
        mock_model.get_power.assert_called_once_with('test_impl', None)

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_get_computing_power_db_empty_powers_falls_back(self, mock_model):
        """数据库返回空配置时应回退到代码默认值"""
        from config.unified_config import UnifiedConfigRegistry

        impl = UnifiedConfigRegistry.get_implementation('test_impl_dict_power')
        mock_model.get_all_powers_for_implementation.return_value = {}

        result = impl.get_computing_power(duration=5, driver_key='TEST_DRIVER')

        self.assertEqual(result, 10)


class TestUnifiedTaskConfigComputingPower(unittest.TestCase):
    """UnifiedTaskConfig 算力获取测试"""

    def setUp(self):
        """测试前准备"""
        from config.unified_config import UnifiedConfigRegistry, UnifiedTaskConfig
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def test_get_computing_power_from_task_config(self):
        """测试从任务配置获取算力（任务配置有权值时）"""
        from config.unified_config import UnifiedConfigRegistry, UnifiedTaskConfig

        config = UnifiedTaskConfig(
            id=999,
            key='test_task',
            name='测试任务',
            category='test',
            provider='test',
            computing_power=10
        )
        UnifiedConfigRegistry.register(config)

        retrieved = UnifiedConfigRegistry.get_by_id(999)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.get_computing_power(), 10)

    def test_get_computing_power_with_implementation(self):
        """测试带 implementation 参数获取算力"""
        from config.unified_config import UnifiedConfigRegistry, UnifiedTaskConfig, ImplementationConfig

        # 注册实现方
        impl = ImplementationConfig(
            name='test_impl_for_power',
            display_name='测试',
            driver_class='TestDriver',
            default_computing_power=8,
            enabled=True
        )
        UnifiedConfigRegistry.register_implementation(impl)

        # 创建任务配置（无算力覆盖，从实现方读取）
        config = UnifiedTaskConfig(
            id=998,
            key='test_task_impl',
            name='测试任务',
            category='test',
            provider='test',
            implementation='test_impl_for_power',
            computing_power=0  # 无覆盖，使用实现方默认值
        )
        UnifiedConfigRegistry.register(config)

        retrieved = UnifiedConfigRegistry.get_by_id(998)
        self.assertIsNotNone(retrieved)
        # 应该从实现方读取
        self.assertEqual(retrieved.get_computing_power(implementation='test_impl_for_power'), 8)


class TestImplementationIdMappingFunctions(unittest.TestCase):
    """实现方 ID 映射函数测试"""

    def test_get_implementation_id(self):
        """测试 get_implementation_id 函数"""
        from config.unified_config import get_implementation_id

        # 已知的映射
        self.assertEqual(get_implementation_id('sora2_duomi_v1'), 1)
        self.assertEqual(get_implementation_id('kling_duomi_v1'), 2)
        self.assertEqual(get_implementation_id('gemini_duomi_v1'), 3)
        self.assertEqual(get_implementation_id('seedream5_volcengine_v1'), 16)

        # 未知的返回 0
        self.assertEqual(get_implementation_id('nonexistent'), 0)

    def test_get_implementation_name(self):
        """测试 get_implementation_name 函数"""
        from config.unified_config import get_implementation_name

        # 已知的映射
        self.assertEqual(get_implementation_name(1), 'sora2_duomi_v1')
        self.assertEqual(get_implementation_name(2), 'kling_duomi_v1')
        self.assertEqual(get_implementation_name(3), 'gemini_duomi_v1')
        self.assertEqual(get_implementation_name(16), 'seedream5_volcengine_v1')

        # 未知的返回 'unknown'
        self.assertEqual(get_implementation_name(999), 'unknown')


class TestSupportsAutoFace(unittest.TestCase):
    """实现方「支持自动处理人脸」能力标识测试

    huimengi 网关内置 human_review 真人审核，标识为 supports_auto_face=True；
    其余 Seedance 2.0 网关（volcengine/oversea/kkidc）保持 False，仍走 RunningHub 遮盖预处理。
    """

    def setUp(self):
        """初始化完整配置（确保 huimengi 等实现方已注册）"""
        from config.unified_config import UnifiedConfigRegistry, init_unified_config
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()
        init_unified_config()

    def tearDown(self):
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def test_huimengi_implementations_support_auto_face(self):
        """huimengi 3 个实现方应标识 supports_auto_face=True"""
        from config.unified_config import UnifiedConfigRegistry
        for impl_name in [
            'seedance_2_0_fast_huimengi_v1',
            'seedance_2_0_huimengi_v1',
            'seedance_2_0_mini_huimengi_v1',
        ]:
            impl = UnifiedConfigRegistry.get_implementation(impl_name)
            with self.subTest(impl_name=impl_name):
                self.assertIsNotNone(impl, f"{impl_name} 未注册")
                self.assertTrue(impl.supports_auto_face, f"{impl_name} 应支持自动处理人脸")

    def test_other_seedance_implementations_do_not_support_auto_face(self):
        """volcengine/oversea/kkidc 的 Seedance 2.0 实现方应保持 supports_auto_face=False"""
        from config.unified_config import UnifiedConfigRegistry
        for impl_name in [
            'seedance_2_0_volcengine_v1',
            'seedance_2_0_fast_volcengine_v1',
            'seedance_2_0_mini_volcengine_v1',
            'seedance_2_0_volcengine_oversea_v1',
            'seedance_2_0_fast_volcengine_oversea_v1',
            'seedance_2_0_mini_volcengine_oversea_v1',
            'seedance_2_0_kkidc_v1',
            'seedance_2_0_fast_kkidc_v1',
            'seedance_2_0_mini_kkidc_v1',
        ]:
            impl = UnifiedConfigRegistry.get_implementation(impl_name)
            with self.subTest(impl_name=impl_name):
                self.assertIsNotNone(impl, f"{impl_name} 未注册")
                self.assertFalse(impl.supports_auto_face, f"{impl_name} 不应支持自动处理人脸")

    def test_supports_auto_face_default_false(self):
        """新增 ImplementationConfig 默认 supports_auto_face=False"""
        from config.unified_config import ImplementationConfig
        impl = ImplementationConfig(
            name='test_auto_face_default',
            display_name='测试',
            driver_class='TestDriver',
        )
        self.assertFalse(impl.supports_auto_face)

    def test_to_dict_includes_supports_auto_face(self):
        """to_dict 应包含 supports_auto_face 字段"""
        from config.unified_config import UnifiedConfigRegistry
        impl = UnifiedConfigRegistry.get_implementation('seedance_2_0_huimengi_v1')
        self.assertIsNotNone(impl)
        d = impl.to_dict()
        self.assertIn('supports_auto_face', d)
        self.assertTrue(d['supports_auto_face'])


class TestDriverImplementationIdConstants(unittest.TestCase):
    """DriverImplementationId 常量测试"""

    def test_all_implementations_have_id(self):
        """测试所有 DriverImplementation 都有对应的 ID"""
        from config.unified_config import (
            DriverImplementation,
            get_implementation_id,
            DriverImplementationId
        )

        # 检查所有 DriverImplementation 字符串都有对应的 ID（非 0）
        impl_attrs = [attr for attr in dir(DriverImplementation) if not attr.startswith('_')]

        for attr in impl_attrs:
            impl_name = getattr(DriverImplementation, attr)
            if isinstance(impl_name, str) and impl_name:
                impl_id = get_implementation_id(impl_name)
                self.assertNotEqual(impl_id, 0,
                    f"DriverImplementation.{attr} ({impl_name}) 没有对应的 ID")

    def test_id_mapping_consistency(self):
        """测试 ID 映射的一致性"""
        from config.unified_config import (
            DriverImplementation,
            DriverImplementationId,
            get_implementation_id,
            get_implementation_name
        )

        # 验证关键映射
        test_cases = [
            ('sora2_duomi_v1', 1),
            ('kling_duomi_v1', 2),
            ('gemini_duomi_v1', 3),
            ('veo3_duomi_v1', 10),
            ('ltx2_runninghub_v1', 11),
            ('wan22_runninghub_v1', 12),
            ('digital_human_runninghub_v1', 13),
            ('seedream5_volcengine_v1', 16),
        ]

        for impl_name, expected_id in test_cases:
            self.assertEqual(get_implementation_id(impl_name), expected_id)
            self.assertEqual(get_implementation_name(expected_id), impl_name)

    def test_implementation_ids_are_unique(self):
        """IMPLEMENTATION_TO_ID / DriverImplementationId 数字 ID 必须全局唯一。

        曾发生 Seedance 2.5 与 MiniMax H3 参考生视频共用 67：
        IMPLEMENTATION_FROM_ID 后写覆盖，落库后再反查会变成 H3 驱动。
        """
        from config.unified_config import (
            DriverImplementationId,
            IMPLEMENTATION_TO_ID,
            IMPLEMENTATION_FROM_ID,
            get_implementation_id,
            get_implementation_name,
        )

        seen_ids = {}
        for impl_name, impl_id in IMPLEMENTATION_TO_ID.items():
            self.assertIsInstance(impl_id, int)
            self.assertGreater(impl_id, 0, f"{impl_name} 的 ID 必须为正整数，实际: {impl_id}")
            previous = seen_ids.get(impl_id)
            self.assertIsNone(
                previous,
                f"实现 ID {impl_id} 被重复占用: {previous} 与 {impl_name}",
            )
            seen_ids[impl_id] = impl_name

        enum_ids = {}
        for attr in dir(DriverImplementationId):
            if attr.startswith('_'):
                continue
            value = getattr(DriverImplementationId, attr)
            if not isinstance(value, int):
                continue
            if attr == 'UNKNOWN':
                self.assertEqual(value, 0)
                continue
            previous = enum_ids.get(value)
            self.assertIsNone(
                previous,
                f"DriverImplementationId.{attr}={value} 与 DriverImplementationId.{previous} 冲突",
            )
            enum_ids[value] = attr

        self.assertEqual(len(IMPLEMENTATION_FROM_ID), len(IMPLEMENTATION_TO_ID))
        for impl_name, impl_id in IMPLEMENTATION_TO_ID.items():
            self.assertEqual(IMPLEMENTATION_FROM_ID[impl_id], impl_name)
            self.assertEqual(get_implementation_name(impl_id), impl_name)
            self.assertEqual(get_implementation_id(impl_name), impl_id)

        self.assertEqual(get_implementation_id('minimax_h3_reference_runninghub_v1'), 67)
        self.assertEqual(get_implementation_name(67), 'minimax_h3_reference_runninghub_v1')
        self.assertEqual(get_implementation_id('seedance_2_5_volcengine_v1'), 68)
        self.assertEqual(get_implementation_name(68), 'seedance_2_5_volcengine_v1')


# 需要先导入 ImplementationConfig
from config.unified_config import ImplementationConfig


if __name__ == '__main__':
    unittest.main()
