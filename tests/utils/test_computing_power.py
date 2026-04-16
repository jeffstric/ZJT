"""
算力计算工具单元测试
测试 utils.computing_power 模块，防止数据库配置与代码默认值回退的回归问题
"""
import unittest
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


if __name__ == '__main__':
    unittest.main()
