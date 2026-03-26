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


# 需要先导入 ImplementationConfig
from config.unified_config import ImplementationConfig


if __name__ == '__main__':
    unittest.main()
