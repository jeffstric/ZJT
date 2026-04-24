"""
算力修饰符配置单元测试
测试 PowerModifier 和任务修饰符配置的完整功能
"""
import unittest
from unittest.mock import patch, MagicMock


class TestPowerModifierClass(unittest.TestCase):
    """测试 PowerModifier 数据类"""

    def test_power_modifier_initialization(self):
        """验证 PowerModifier 可以正确初始化"""
        from config.unified_config import PowerModifier

        modifier = PowerModifier(
            attribute='image_mode',
            values={
                'first_last_with_tail': 1.66,
                'first_last_frame': 1.0,
            },
            default=1.0
        )

        self.assertEqual(modifier.attribute, 'image_mode')
        self.assertEqual(modifier.values['first_last_with_tail'], 1.66)
        self.assertEqual(modifier.values['first_last_frame'], 1.0)
        self.assertEqual(modifier.default, 1.0)

    def test_power_modifier_with_custom_default(self):
        """验证 PowerModifier 支持自定义 default 值"""
        from config.unified_config import PowerModifier

        modifier = PowerModifier(
            attribute='resolution',
            values={'2K': 1.5, '4K': 2.5},
            default=1.1  # 自定义默认值
        )

        self.assertEqual(modifier.default, 1.1)


class TestTaskConfigWithModifiers(unittest.TestCase):
    """测试包含修饰符的任务配置"""

    def setUp(self):
        """测试前准备"""
        from config.unified_config import (
            UnifiedConfigRegistry,
            UnifiedTaskConfig,
            PowerModifier,
            TaskCategory,
            TaskProvider,
        )

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

        # 注册 Kling 图生视频任务（带修饰符）
        UnifiedConfigRegistry.register(
            UnifiedTaskConfig(
                id=9999,
                key='kling_test_video',
                name='测试 Kling 视频',
                category=TaskCategory.IMAGE_TO_VIDEO,
                provider=TaskProvider.DUOMI,
                computing_power={5: 38, 10: 70},
                supported_durations=[5, 10],
                default_duration=5,
                power_modifiers=[
                    PowerModifier(
                        attribute='image_mode',
                        values={
                            'first_last_with_tail': 1.66,
                            'first_last_frame': 1.0,
                        },
                        default=1.0
                    )
                ],
                sort_order=100,
            )
        )

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def test_task_has_power_modifiers_field(self):
        """验证任务配置包含 power_modifiers 字段"""
        from config.unified_config import UnifiedConfigRegistry

        task = UnifiedConfigRegistry.get_by_id(9999)

        self.assertIsNotNone(task)
        self.assertTrue(hasattr(task, 'power_modifiers'))
        self.assertEqual(len(task.power_modifiers), 1)

    def test_modifier_passed_to_frontend_dict(self):
        """验证修饰符信息被传递到前端"""
        from config.unified_config import UnifiedConfigRegistry

        task = UnifiedConfigRegistry.get_by_id(9999)
        frontend_dict = task.to_frontend_dict()

        self.assertIn('power_modifiers', frontend_dict)
        modifiers = frontend_dict['power_modifiers']
        self.assertEqual(len(modifiers), 1)
        self.assertEqual(modifiers[0]['attribute'], 'image_mode')
        self.assertIn('first_last_with_tail', modifiers[0]['values'])
        self.assertEqual(modifiers[0]['values']['first_last_with_tail'], 1.66)

    def test_get_power_modifiers_map_includes_task(self):
        """验证 get_power_modifiers_map 包含该任务的修饰符"""
        from config.unified_config import UnifiedConfigRegistry

        modifiers_map = UnifiedConfigRegistry.get_power_modifiers_map()

        self.assertIn(9999, modifiers_map)
        self.assertEqual(len(modifiers_map[9999]), 1)
        self.assertEqual(modifiers_map[9999][0]['attribute'], 'image_mode')

    def test_get_computing_power_with_context_applies_modifier(self):
        """验证 get_computing_power 应用修饰符"""
        from config.unified_config import UnifiedConfigRegistry

        task = UnifiedConfigRegistry.get_by_id(9999)

        # 不传 context，应返回基础算力
        power_without_context = task.get_computing_power(duration=5)
        self.assertEqual(power_without_context, 38)

        # 传 context，应应用修饰符
        power_with_modifier = task.get_computing_power(
            duration=5,
            context={'image_mode': 'first_last_with_tail'}
        )
        # 38 × 1.66 = 63.08，向上取整 = 64
        self.assertEqual(power_with_modifier, 64)


class TestTaskConfigToFrontendWithModifiers(unittest.TestCase):
    """测试前端配置格式包含修饰符"""

    def setUp(self):
        """测试前准备"""
        from config.unified_config import (
            UnifiedConfigRegistry,
            init_unified_config,
        )

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

        # 初始化完整配置
        init_unified_config()

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def test_frontend_config_includes_power_modifiers_for_kling(self):
        """验证前端配置包含 Kling 的修饰符信息"""
        from config.unified_config import UnifiedConfigRegistry

        frontend_config = UnifiedConfigRegistry.get_frontend_config()

        # 查找 kling_image_to_video 任务
        kling_task = None
        for task in frontend_config['tasks']:
            if task['key'] == 'kling_image_to_video':
                kling_task = task
                break

        self.assertIsNotNone(kling_task, "未找到 kling_image_to_video 任务")
        self.assertIn('power_modifiers', kling_task)

        modifiers = kling_task['power_modifiers']
        self.assertEqual(len(modifiers), 1)
        self.assertEqual(modifiers[0]['attribute'], 'image_mode')
        self.assertIn('first_last_with_tail', modifiers[0]['values'])
        self.assertEqual(modifiers[0]['values']['first_last_with_tail'], 1.66)

    def test_frontend_config_power_modifiers_map(self):
        """验证 get_power_modifiers_map 包含所有任务的修饰符"""
        from config.unified_config import UnifiedConfigRegistry

        modifiers_map = UnifiedConfigRegistry.get_power_modifiers_map()

        # 应该是一个字典，key 是任务 ID，value 是修饰符列表
        self.assertIsInstance(modifiers_map, dict)

        # Kling 任务应该在其中（ID=12）
        kling_task_id = 12  # 根据配置中 KLING_IMAGE_TO_VIDEO = 12
        self.assertIn(kling_task_id, modifiers_map)
        self.assertIsInstance(modifiers_map[kling_task_id], list)

        # 验证修饰符结构
        for modifier in modifiers_map[kling_task_id]:
            self.assertIn('attribute', modifier)
            self.assertIn('values', modifier)
            self.assertIn('default', modifier)


class TestModifierCeilingBehavior(unittest.TestCase):
    """测试修饰符应用时的向上取整行为"""

    def setUp(self):
        """测试前准备"""
        from config.unified_config import (
            UnifiedConfigRegistry,
            UnifiedTaskConfig,
            PowerModifier,
            TaskCategory,
            TaskProvider,
        )

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

        # 注册多个测试任务，用于测试不同的取整情况
        UnifiedConfigRegistry.register(
            UnifiedTaskConfig(
                id=8001,
                key='ceil_test_1',
                name='测试取整 1',
                category=TaskCategory.IMAGE_EDIT,
                provider=TaskProvider.DUOMI,
                computing_power=100,
                power_modifiers=[
                    PowerModifier(
                        attribute='quality',
                        values={'high': 1.01},
                        default=1.0
                    )
                ],
                sort_order=200,
            )
        )

        UnifiedConfigRegistry.register(
            UnifiedTaskConfig(
                id=8002,
                key='ceil_test_2',
                name='测试取整 2',
                category=TaskCategory.IMAGE_EDIT,
                provider=TaskProvider.DUOMI,
                computing_power=100,
                power_modifiers=[
                    PowerModifier(
                        attribute='quality',
                        values={'high': 1.001},
                        default=1.0
                    )
                ],
                sort_order=210,
            )
        )

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def test_ceiling_101_percent(self):
        """测试 100 × 1.01 = 101（向上取整）"""
        from config.unified_config import UnifiedConfigRegistry

        task = UnifiedConfigRegistry.get_by_id(8001)
        result = task.get_computing_power(context={'quality': 'high'})

        # 100 × 1.01 = 101.0，向上取整 = 101
        self.assertEqual(result, 101)

    def test_ceiling_100_1_percent(self):
        """测试 100 × 1.001 = 100.1（向上取整 = 101）"""
        from config.unified_config import UnifiedConfigRegistry

        task = UnifiedConfigRegistry.get_by_id(8002)
        result = task.get_computing_power(context={'quality': 'high'})

        # 100 × 1.001 = 100.1，向上取整 = 101
        self.assertEqual(result, 101)


if __name__ == '__main__':
    unittest.main()
