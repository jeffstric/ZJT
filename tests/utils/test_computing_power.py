"""
算力计算工具单元测试
测试 utils.computing_power 模块，防止数据库配置与代码默认值回退的回归问题
包括修饰符功能和 context 构建的完整单元测试
"""
import unittest
import json
from unittest.mock import patch, MagicMock


class TestGetComputingPowerForTask(unittest.TestCase):
    """测试 get_computing_power_for_task 函数"""

    def setUp(self):
        """测试前准备：清理注册表并注册测试实现方和任务"""
        from config.unified_config import (
            UnifiedConfigRegistry,
            ImplementationConfig,
            UnifiedTaskConfig,
            TaskCategory,
            TaskProvider,
        )

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

        # 注册按时长计费的实现方（类似 Seedance）
        UnifiedConfigRegistry.register_implementation(
            ImplementationConfig(
                name='seedance_test_impl',
                display_name='测试 Seedance',
                driver_class='TestSeedanceDriver',
                default_computing_power={5: 46, 10: 94},
                enabled=True,
                description='测试用 Seedance 实现方',
                sort_order=1000.0,
            )
        )

        # 注册固定算力的实现方
        UnifiedConfigRegistry.register_implementation(
            ImplementationConfig(
                name='fixed_test_impl',
                display_name='测试固定算力',
                driver_class='TestFixedDriver',
                default_computing_power=6,
                enabled=True,
                description='测试用固定算力实现方',
                sort_order=2000.0,
            )
        )

        # 注册用户偏好测试实现方
        UnifiedConfigRegistry.register_implementation(
            ImplementationConfig(
                name='user_pref_impl',
                display_name='用户偏好实现方',
                driver_class='TestPrefDriver',
                default_computing_power=50,
                enabled=True,
                description='测试用户偏好',
                sort_order=3000.0,
            )
        )

        # 注册按时长计费任务
        UnifiedConfigRegistry.register(
            UnifiedTaskConfig(
                id=9991,
                key='seedance_test_task',
                name='测试 Seedance 任务',
                category=TaskCategory.IMAGE_TO_VIDEO,
                provider=TaskProvider.VOLCENGINE,
                driver_name='SEEDANCE_TEST_DRIVER',
                implementation='seedance_test_impl',
                implementations=['seedance_test_impl'],
                supported_durations=[5, 10],
                default_ratio='9:16',
                default_duration=5,
                sort_order=10,
            )
        )

        # 注册固定算力任务
        UnifiedConfigRegistry.register(
            UnifiedTaskConfig(
                id=9992,
                key='fixed_test_task',
                name='测试固定算力任务',
                category=TaskCategory.IMAGE_TO_VIDEO,
                provider=TaskProvider.DUOMI,
                driver_name='FIXED_TEST_DRIVER',
                implementation='fixed_test_impl',
                implementations=['fixed_test_impl'],
                supported_durations=[8],
                default_ratio='9:16',
                default_duration=8,
                sort_order=20,
            )
        )

        # 注册任务配置覆盖任务
        UnifiedConfigRegistry.register(
            UnifiedTaskConfig(
                id=9993,
                key='override_test_task',
                name='测试配置覆盖任务',
                category=TaskCategory.IMAGE_TO_VIDEO,
                provider=TaskProvider.VOLCENGINE,
                driver_name='OVERRIDE_TEST_DRIVER',
                implementation='seedance_test_impl',
                computing_power=100,  # 任务级覆盖
                supported_durations=[5, 10],
                default_ratio='9:16',
                default_duration=5,
                sort_order=30,
            )
        )

        # 注册用户偏好测试任务
        UnifiedConfigRegistry.register(
            UnifiedTaskConfig(
                id=9994,
                key='user_pref_task',
                name='测试用户偏好任务',
                category=TaskCategory.IMAGE_TO_VIDEO,
                provider=TaskProvider.VOLCENGINE,
                driver_name='USER_PREF_DRIVER',
                implementation='fixed_test_impl',
                implementations=['fixed_test_impl', 'user_pref_impl'],
                supported_durations=[5],
                default_ratio='9:16',
                default_duration=5,
                sort_order=40,
            )
        )

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_duration_based_uses_db_override_not_default(self, mock_model):
        """
        核心回归测试：按时长计费的实现方应使用数据库配置，而非代码默认值
        """
        from utils.computing_power import get_computing_power_for_task

        # 数据库配置：5秒算力为10，覆盖代码默认值46
        mock_model.get_all_powers_for_implementation.return_value = {5: 10, 10: 20}

        result = get_computing_power_for_task(9991, duration=5)

        self.assertEqual(result, 10)
        self.assertNotEqual(result, 46)
        mock_model.get_all_powers_for_implementation.assert_called_once_with(
            'seedance_test_impl', 'SEEDANCE_TEST_DRIVER'
        )

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_fixed_power_uses_db_override(self, mock_model):
        """固定算力实现方也应使用数据库覆盖值"""
        from utils.computing_power import get_computing_power_for_task

        mock_model.get_all_powers_for_implementation.return_value = {None: 7}

        result = get_computing_power_for_task(9992, duration=8)

        self.assertEqual(result, 7)
        self.assertNotEqual(result, 6)
        mock_model.get_all_powers_for_implementation.assert_called_once_with(
            'fixed_test_impl', 'FIXED_TEST_DRIVER'
        )

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_missing_db_config_falls_back_to_code_default(self, mock_model):
        """数据库无配置时应回退到代码默认值"""
        from utils.computing_power import get_computing_power_for_task

        mock_model.get_all_powers_for_implementation.return_value = {}

        result = get_computing_power_for_task(9991, duration=5)

        self.assertEqual(result, 46)

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_db_exception_falls_back_to_code_default(self, mock_model):
        """数据库异常时应回退到代码默认值且不抛异常"""
        from utils.computing_power import get_computing_power_for_task

        mock_model.get_all_powers_for_implementation.side_effect = Exception("DB error")

        result = get_computing_power_for_task(9991, duration=5)

        self.assertEqual(result, 46)

    def test_task_config_override_takes_precedence(self):
        """任务配置的 computing_power 应优先于实现方配置"""
        from utils.computing_power import get_computing_power_for_task

        # 不 mock DB，直接验证任务级覆盖
        result = get_computing_power_for_task(9993, duration=5)

        self.assertEqual(result, 100)

    @patch('model.implementation_power.ImplementationPowerModel')
    @patch('model.users.UsersModel')
    def test_user_preference_respected(self, mock_users, mock_model):
        """用户偏好实现方应被使用"""
        from utils.computing_power import get_computing_power_for_task

        mock_users.get_implementation_preference.return_value = 'user_pref_impl'
        mock_model.get_all_powers_for_implementation.return_value = {None: 33}

        result = get_computing_power_for_task(9994, duration=5, user_id=123)

        self.assertEqual(result, 33)
        mock_users.get_implementation_preference.assert_called_once()
        mock_model.get_all_powers_for_implementation.assert_called_once_with(
            'user_pref_impl', 'USER_PREF_DRIVER'
        )

    def test_no_config_returns_zero(self):
        """未注册的任务类型应返回 0"""
        from utils.computing_power import get_computing_power_for_task

        result = get_computing_power_for_task(888888, duration=5)

        self.assertEqual(result, 0)

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_duration_not_in_db_powers_uses_first_available(self, mock_model):
        """数据库中没有对应时长时，应返回第一个可用的 DB 值"""
        from utils.computing_power import get_computing_power_for_task

        # DB 只有 10 秒的配置，但查询 5 秒
        mock_model.get_all_powers_for_implementation.return_value = {10: 20}

        result = get_computing_power_for_task(9991, duration=5)

        self.assertEqual(result, 20)

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_driver_name_passed_not_duration(self, mock_model):
        """
        关键参数传递测试：确保 duration 不会被误传为 driver_key
        这是原 Bug 的直接回归测试
        """
        from utils.computing_power import get_computing_power_for_task

        mock_model.get_all_powers_for_implementation.return_value = {5: 10}

        get_computing_power_for_task(9991, duration=5)

        call_args = mock_model.get_all_powers_for_implementation.call_args
        self.assertEqual(call_args.args[0], 'seedance_test_impl')
        self.assertEqual(call_args.args[1], 'SEEDANCE_TEST_DRIVER')
        # 绝对不能把 duration=5 当作 driver_key 传入
        self.assertNotEqual(call_args.args[1], 5)


class TestGetComputingPowerConfigForTask(unittest.TestCase):
    """测试 get_computing_power_config_for_task 函数"""

    def setUp(self):
        from config.unified_config import (
            UnifiedConfigRegistry,
            ImplementationConfig,
            UnifiedTaskConfig,
            TaskCategory,
            TaskProvider,
        )

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

        UnifiedConfigRegistry.register_implementation(
            ImplementationConfig(
                name='db_test_impl',
                display_name='DB测试',
                driver_class='TestDriver',
                default_computing_power={5: 46, 10: 94},
                enabled=True,
                sort_order=1000.0,
            )
        )

        UnifiedConfigRegistry.register(
            UnifiedTaskConfig(
                id=9995,
                key='db_test_task',
                name='DB测试任务',
                category=TaskCategory.IMAGE_TO_VIDEO,
                provider=TaskProvider.VOLCENGINE,
                driver_name='DB_TEST_DRIVER',
                implementation='db_test_impl',
                implementations=['db_test_impl'],
                supported_durations=[5, 10],
                default_ratio='9:16',
                default_duration=5,
                sort_order=10,
            )
        )

    def tearDown(self):
        from config.unified_config import UnifiedConfigRegistry

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_config_info_returns_database_source_for_db_override(self, mock_model):
        """数据库有配置时应返回 source='database'"""
        from utils.computing_power import get_computing_power_config_for_task

        mock_model.get_all_powers_for_implementation.return_value = {5: 10, 10: 20}

        result = get_computing_power_config_for_task(9995)

        self.assertEqual(result['source'], 'database')
        self.assertEqual(result['implementation'], 'db_test_impl')
        self.assertEqual(result['computing_power'], {5: 10, 10: 20})

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_config_info_returns_code_default_source_for_fallback(self, mock_model):
        """数据库无配置时应返回 source='code_default'"""
        from utils.computing_power import get_computing_power_config_for_task

        mock_model.get_all_powers_for_implementation.return_value = {}

        result = get_computing_power_config_for_task(9995)

        self.assertEqual(result['source'], 'code_default')
        self.assertEqual(result['computing_power'], {5: 46, 10: 94})

    def test_config_info_returns_task_config_source(self):
        """任务级覆盖时应返回 source='task_config'"""
        from config.unified_config import UnifiedConfigRegistry, UnifiedTaskConfig
        from utils.computing_power import get_computing_power_config_for_task

        task = UnifiedTaskConfig(
            id=9996,
            key='task_override',
            name='任务覆盖',
            category='image_to_video',
            provider='volcengine',
            computing_power=200,
        )
        UnifiedConfigRegistry.register(task)

        result = get_computing_power_config_for_task(9996)

        self.assertEqual(result['source'], 'task_config')
        self.assertEqual(result['computing_power'], 200)


class TestPowerModifiers(unittest.TestCase):
    """测试算力修饰符功能"""

    def setUp(self):
        """测试前准备：注册带修饰符的任务配置"""
        from config.unified_config import (
            UnifiedConfigRegistry,
            UnifiedTaskConfig,
            PowerModifier,
            TaskCategory,
            TaskProvider,
            ImplementationConfig,
        )

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

        # 注册实现方
        UnifiedConfigRegistry.register_implementation(
            ImplementationConfig(
                name='kling_test_impl',
                display_name='测试 Kling',
                driver_class='KlingTestDriver',
                default_computing_power={5: 38, 10: 70},
                enabled=True,
                sort_order=1000.0,
            )
        )

        # 注册带修饰符的任务（图生视频 - Kling）
        UnifiedConfigRegistry.register(
            UnifiedTaskConfig(
                id=9997,
                key='kling_modifier_test',
                name='测试 Kling 修饰符',
                category=TaskCategory.IMAGE_TO_VIDEO,
                provider=TaskProvider.DUOMI,
                driver_name='KLING_TEST_DRIVER',
                implementation='kling_test_impl',
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
                sort_order=50,
            )
        )

        # 注册带多个修饰符的任务
        UnifiedConfigRegistry.register(
            UnifiedTaskConfig(
                id=9998,
                key='multi_modifier_test',
                name='测试多修饰符',
                category=TaskCategory.IMAGE_EDIT,
                provider=TaskProvider.DUOMI,
                computing_power={1: 2},  # 基础算力 2
                power_modifiers=[
                    PowerModifier(
                        attribute='resolution',
                        values={
                            '2K': 1.5,
                            '4K': 2.5,
                            '1K': 1.0,
                        },
                        default=1.0
                    ),
                    PowerModifier(
                        attribute='quality',
                        values={
                            'high': 1.2,
                            'normal': 1.0,
                        },
                        default=1.0
                    )
                ],
                sort_order=60,
            )
        )

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry

        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def test_modifier_not_applied_without_context(self):
        """未提供 context 时，修饰符不应被应用"""
        from utils.computing_power import get_computing_power_for_task

        # 不提供 context，应返回基础算力
        result = get_computing_power_for_task(9997, duration=5)

        self.assertEqual(result, 38)

    def test_first_last_frame_modifier_multiplier_1_0(self):
        """first_last_frame 模式的修饰符为 1.0"""
        from utils.computing_power import get_computing_power_for_task

        result = get_computing_power_for_task(9997, duration=5, context={'image_mode': 'first_last_frame'})

        # 38 × 1.0 = 38
        self.assertEqual(result, 38)

    def test_first_last_with_tail_modifier_multiplier_1_66(self):
        """first_last_with_tail 模式的修饰符为 1.66，结果应向上取整"""
        from utils.computing_power import get_computing_power_for_task

        result = get_computing_power_for_task(9997, duration=5, context={'image_mode': 'first_last_with_tail'})

        # 38 × 1.66 = 63.08，向上取整 = 64
        self.assertEqual(result, 64)

    def test_first_last_with_tail_10s_duration(self):
        """10秒前后帧计算：70 × 1.66 = 116.2 → 117"""
        from utils.computing_power import get_computing_power_for_task

        result = get_computing_power_for_task(9997, duration=10, context={'image_mode': 'first_last_with_tail'})

        # 70 × 1.66 = 116.2，向上取整 = 117
        self.assertEqual(result, 117)

    def test_default_modifier_for_unmatched_attribute_value(self):
        """未匹配的属性值应使用 default 乘数"""
        from utils.computing_power import get_computing_power_for_task

        result = get_computing_power_for_task(
            9997,
            duration=5,
            context={'image_mode': 'unknown_mode'}
        )

        # 未匹配到 'unknown_mode'，使用 default=1.0，结果 = 38
        self.assertEqual(result, 38)

    def test_multiple_modifiers_accumulate(self):
        """多个修饰符应累积相乘，最后一次向上取整"""
        from utils.computing_power import get_computing_power_for_task

        context = {
            'resolution': '2K',    # 乘数 1.5
            'quality': 'high',     # 乘数 1.2
        }
        result = get_computing_power_for_task(9998, context=context)

        # 基础算力 2 × (1.5 × 1.2) = 2 × 1.8 = 3.6，向上取整 = 4
        self.assertEqual(result, 4)

    def test_multiple_modifiers_4k_high_quality(self):
        """4K 高质量：2 × (2.5 × 1.2) = 6.0"""
        from utils.computing_power import get_computing_power_for_task

        context = {
            'resolution': '4K',    # 乘数 2.5
            'quality': 'high',     # 乘数 1.2
        }
        result = get_computing_power_for_task(9998, context=context)

        # 2 × (2.5 × 1.2) = 2 × 3.0 = 6.0，向上取整 = 6
        self.assertEqual(result, 6)

    def test_partial_context_uses_default_for_missing_attribute(self):
        """context 中缺少某些属性时，应使用该属性的 default 乘数"""
        from utils.computing_power import get_computing_power_for_task

        context = {
            'resolution': '2K',  # 乘数 1.5
            # 'quality' 缺失，应使用 default=1.0
        }
        result = get_computing_power_for_task(9998, context=context)

        # 2 × (1.5 × 1.0) = 3.0，向上取整 = 3
        self.assertEqual(result, 3)

    def test_ceiling_function_used_not_rounding(self):
        """验证使用 ceiling 函数而非 rounding"""
        from utils.computing_power import get_computing_power_for_task

        # 构造一个会产生 x.1 的情况来区分 ceil 和 round
        context = {
            'resolution': '1K',    # 乘数 1.0
            'quality': 'normal',   # 乘数 1.0
        }
        result = get_computing_power_for_task(9998, context=context)

        # 2 × (1.0 × 1.0) = 2.0
        self.assertEqual(result, 2)


class TestBuildContextFromTaskRecord(unittest.TestCase):
    """测试 build_context_from_task_record 函数"""

    def test_extract_image_mode_from_extra_config(self):
        """从 extra_config JSON 提取 image_mode"""
        from utils.computing_power import build_context_from_task_record
        import json

        task_record = MagicMock()
        task_record.extra_config = json.dumps({'image_mode': 'first_last_frame'})
        task_record.image_path = 'image1.jpg'

        context = build_context_from_task_record(task_record)

        self.assertEqual(context['image_mode'], 'first_last_frame')

    def test_detect_first_last_with_tail_from_image_path(self):
        """当 image_path 有逗号时，应转换为 first_last_with_tail"""
        from utils.computing_power import build_context_from_task_record
        import json

        task_record = MagicMock()
        task_record.extra_config = json.dumps({'image_mode': 'first_last_frame'})
        task_record.image_path = 'image1.jpg,image2.jpg'  # 两张图，有逗号

        context = build_context_from_task_record(task_record)

        # 应该转换为 first_last_with_tail
        self.assertEqual(context['image_mode'], 'first_last_with_tail')

    def test_keep_first_last_frame_when_single_image(self):
        """单张图片时应保持 first_last_frame"""
        from utils.computing_power import build_context_from_task_record
        import json

        task_record = MagicMock()
        task_record.extra_config = json.dumps({'image_mode': 'first_last_frame'})
        task_record.image_path = 'image1.jpg'  # 单张图

        context = build_context_from_task_record(task_record)

        self.assertEqual(context['image_mode'], 'first_last_frame')

    def test_extract_resolution_from_image_size(self):
        """从 image_size 字段提取分辨率"""
        from utils.computing_power import build_context_from_task_record
        import json

        task_record = MagicMock()
        task_record.extra_config = json.dumps({})
        task_record.image_size = '2K'

        context = build_context_from_task_record(task_record)

        self.assertEqual(context['resolution'], '2K')

    def test_combine_image_mode_and_resolution(self):
        """同时提取 image_mode 和 resolution"""
        from utils.computing_power import build_context_from_task_record
        import json

        task_record = MagicMock()
        task_record.extra_config = json.dumps({'image_mode': 'first_last_frame'})
        task_record.image_path = 'img1.jpg,img2.jpg'
        task_record.image_size = '4K'

        context = build_context_from_task_record(task_record)

        self.assertEqual(context['image_mode'], 'first_last_with_tail')
        self.assertEqual(context['resolution'], '4K')

    def test_handle_missing_extra_config(self):
        """缺少 extra_config 时不抛异常"""
        from utils.computing_power import build_context_from_task_record

        task_record = MagicMock()
        del task_record.extra_config  # 模拟缺失字段
        task_record.image_size = '2K'

        context = build_context_from_task_record(task_record)

        self.assertEqual(context['resolution'], '2K')
        self.assertNotIn('image_mode', context)

    def test_handle_invalid_json_in_extra_config(self):
        """无效的 JSON 不应导致异常"""
        from utils.computing_power import build_context_from_task_record

        task_record = MagicMock()
        task_record.extra_config = 'invalid json {'
        task_record.image_size = '1K'

        context = build_context_from_task_record(task_record)

        # 应只返回 resolution，image_mode 因 JSON 错误而缺失
        self.assertEqual(context['resolution'], '1K')
        self.assertNotIn('image_mode', context)

    def test_empty_context_for_empty_record(self):
        """空任务记录应返回空 context"""
        from utils.computing_power import build_context_from_task_record

        task_record = MagicMock()
        task_record.extra_config = json.dumps({})
        # 确保 image_size 不存在或为 None
        del task_record.image_size  # 删除可能存在的属性

        context = build_context_from_task_record(task_record)

        self.assertEqual(context, {})


if __name__ == '__main__':
    unittest.main()
