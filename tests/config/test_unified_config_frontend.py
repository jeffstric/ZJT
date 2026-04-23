"""
前端配置相关单元测试
测试 UnifiedConfigRegistry.get_frontend_config 方法，特别是用户偏好算力功能
"""
import unittest
from unittest.mock import patch, MagicMock


class TestGetFrontendConfig(unittest.TestCase):
    """get_frontend_config 方法测试"""

    def setUp(self):
        """测试前准备"""
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

        # 初始化配置
        from config.unified_config import init_unified_config
        init_unified_config()

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def test_get_frontend_config_without_user_prefs(self):
        """测试不带用户偏好时返回默认配置"""
        from config.unified_config import UnifiedConfigRegistry

        config = UnifiedConfigRegistry.get_frontend_config()

        self.assertIn('tasks', config)
        self.assertIn('categories', config)
        self.assertIn('providers', config)
        self.assertIsInstance(config['tasks'], list)
        self.assertGreater(len(config['tasks']), 0)

    def test_get_frontend_config_with_empty_user_prefs(self):
        """测试带空用户偏好时使用 implementations 排序第一位的算力"""
        from config.unified_config import UnifiedConfigRegistry

        config = UnifiedConfigRegistry.get_frontend_config(user_id=1, user_prefs={})

        self.assertIn('tasks', config)
        self.assertIn('categories', config)
        # 验证任务使用了 implementations 中排序第一位的算力
        # 找到 gemini-2.5-flash-image-preview 任务
        for task in config['tasks']:
            if task.get('key') == 'gemini-2.5-flash-image-preview':
                # 该任务的 implementations 第一位应该是 gemini_image_preview_site2_v1 (sort_order=2000)
                impls = task.get('implementations', [])
                if impls:
                    first_impl = impls[0]
                    expected_power = first_impl.get('computing_power')
                    self.assertEqual(task.get('computing_power'), expected_power,
                        f"应该使用 implementations 第一位的算力 {expected_power}，实际为 {task.get('computing_power')}")
                break

    def test_get_frontend_config_with_user_prefs_no_matching_task(self):
        """测试用户偏好不匹配任何任务时返回默认配置"""
        from config.unified_config import UnifiedConfigRegistry

        # 用户偏好设置了一个不存在的 task_key
        user_prefs = {
            'nonexistent_task_key': 'some_implementation'
        }

        config = UnifiedConfigRegistry.get_frontend_config(user_id=1, user_prefs=user_prefs)

        self.assertIn('tasks', config)
        # 所有任务的 computing_power 应该保持默认（未修改）

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_get_frontend_config_with_user_prefs_applies_power(self, mock_impl_power_model):
        """测试用户偏好会应用对应实现方的算力"""
        from config.unified_config import UnifiedConfigRegistry

        # Mock ImplementationPowerModel methods
        mock_impl_power_model.get_all_powers_for_implementation.return_value = {None: 4}
        mock_impl_power_model.get_config.return_value = {}

        # 获取默认配置（无偏好）作为基准
        default_config = UnifiedConfigRegistry.get_frontend_config()

        # 找到第一个有 computing_power 的任务
        task_with_power = None
        for task in default_config['tasks']:
            if task.get('computing_power') is not None:
                task_with_power = task
                break

        if not task_with_power:
            self.skipTest("没有找到有算力配置的任务，跳过此测试")

        task_key = task_with_power['key']
        default_power = task_with_power.get('computing_power')

        # 设置用户偏好：让该任务使用 gemini_duomi_v1 实现方
        user_prefs = {
            task_key: 'gemini_duomi_v1'
        }

        # 获取带偏好的配置
        config_with_prefs = UnifiedConfigRegistry.get_frontend_config(
            user_id=1,
            user_prefs=user_prefs
        )

        # 找到同一任务，检查算力是否被更新
        updated_task = None
        for task in config_with_prefs['tasks']:
            if task['key'] == task_key:
                updated_task = task
                break

        self.assertIsNotNone(updated_task)
        # 如果用户偏好的实现方算力获取成功，应该返回 4
        mock_impl_power_model.get_all_powers_for_implementation.assert_called()
        self.assertEqual(updated_task.get('computing_power'), 4)
        self.assertEqual(updated_task.get('user_preferred_implementation'), 'gemini_duomi_v1')

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_get_frontend_config_with_user_prefs_db_returns_empty_fallback_to_impl(self, mock_impl_power_model):
        """测试用户偏好设置但数据库返回空时，从 implementations 列表中获取算力（回退机制）"""
        from config.unified_config import UnifiedConfigRegistry

        # Mock ImplementationPowerModel methods - 返回空字典模拟数据库无配置
        mock_impl_power_model.get_all_powers_for_implementation.return_value = {}
        mock_impl_power_model.get_config.return_value = {}

        # 找到一个有 implementations 列表的任务（如 grok_image_to_video）
        default_config = UnifiedConfigRegistry.get_frontend_config()
        
        task_with_impls = None
        for task in default_config['tasks']:
            if task.get('key') == 'grok_image_to_video' and task.get('implementations'):
                task_with_impls = task
                break

        if not task_with_impls:
            self.skipTest("没有找到 grok_image_to_video 任务，跳过此测试")

        task_key = task_with_impls['key']
        implementations = task_with_impls.get('implementations', [])
        
        # 找到用户偏好的实现方（如 grok_duomi_v1）
        preferred_impl = None
        for impl in implementations:
            if impl.get('name') == 'grok_duomi_v1':
                preferred_impl = impl
                break
        
        if not preferred_impl:
            self.skipTest("没有找到 grok_duomi_v1 实现方，跳过此测试")

        expected_power = preferred_impl.get('computing_power')

        # 设置用户偏好
        user_prefs = {
            task_key: 'grok_duomi_v1'
        }

        # 获取带偏好的配置
        config_with_prefs = UnifiedConfigRegistry.get_frontend_config(
            user_id=1,
            user_prefs=user_prefs
        )

        # 找到同一任务
        updated_task = None
        for task in config_with_prefs['tasks']:
            if task['key'] == task_key:
                updated_task = task
                break

        self.assertIsNotNone(updated_task)
        # 当数据库返回空配置时，应该从 implementations 列表中获取算力（回退机制）
        self.assertEqual(updated_task.get('computing_power'), expected_power,
            f"数据库无配置时应该从 implementations 获取算力 {expected_power}，实际为 {updated_task.get('computing_power')}")
        self.assertEqual(updated_task.get('user_preferred_implementation'), 'grok_duomi_v1')

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_get_frontend_config_with_user_prefs_get_power_returns_none(self, mock_impl_power_model):
        """测试用户偏好设置但算力获取返回空时，从 implementations 列表中获取算力"""
        from config.unified_config import UnifiedConfigRegistry

        # Mock ImplementationPowerModel methods
        mock_impl_power_model.get_all_powers_for_implementation.return_value = {}
        mock_impl_power_model.get_config.return_value = {}

        # 获取默认配置（无偏好）作为基准
        default_config = UnifiedConfigRegistry.get_frontend_config()

        # 找到第一个有 computing_power 的任务
        task_with_power = None
        for task in default_config['tasks']:
            if task.get('computing_power') is not None:
                task_with_power = task
                break

        if not task_with_power:
            self.skipTest("没有找到有算力配置的任务，跳过此测试")

        task_key = task_with_power['key']
        default_power = task_with_power.get('computing_power')

        # 设置用户偏好
        user_prefs = {
            task_key: 'gemini_duomi_v1'
        }

        # 获取带偏好的配置
        config_with_prefs = UnifiedConfigRegistry.get_frontend_config(
            user_id=1,
            user_prefs=user_prefs
        )

        # 找到同一任务
        updated_task = None
        for task in config_with_prefs['tasks']:
            if task['key'] == task_key:
                updated_task = task
                break

        self.assertIsNotNone(updated_task)
        # 算力应该从 implementations 列表中获取
        impls = task_with_power.get('implementations', [])
        if impls:
            first_impl = impls[0]
            expected_power = first_impl.get('computing_power')
            self.assertEqual(updated_task.get('computing_power'), expected_power,
                f"应该使用 implementations 第一位的算力 {expected_power}，实际为 {updated_task.get('computing_power')}")
        else:
            self.assertEqual(updated_task.get('computing_power'), default_power)


class TestApplyUserPreferencesToTasks(unittest.TestCase):
    """_apply_user_preferences_to_tasks 方法测试"""

    def setUp(self):
        """测试前准备"""
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

        from config.unified_config import init_unified_config
        init_unified_config()

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def test_apply_user_preferences_empty_prefs_uses_first_impl_power(self):
        """测试空偏好列表时，使用 implementations 中排序第一位的算力"""
        from config.unified_config import UnifiedConfigRegistry

        # 模拟 tasks 有 implementations 列表（按 sort_order 排序）
        tasks = [
            {
                'key': 'task1',
                'computing_power': 2,  # 原始默认值
                'driver_name': 'GEMINI_IMAGE_EDIT',
                'implementations': [
                    {'name': 'impl_a', 'computing_power': 5, 'sort_order': 100},
                    {'name': 'impl_b', 'computing_power': 3, 'sort_order': 200},
                ]
            },
            {
                'key': 'task2',
                'computing_power': 3,
                'driver_name': 'GEMINI_IMAGE_EDIT',
                'implementations': [
                    {'name': 'impl_c', 'computing_power': 7, 'sort_order': 50},
                ]
            },
        ]

        result = UnifiedConfigRegistry._apply_user_preferences_to_tasks(tasks, {})

        self.assertEqual(len(result), 2)
        # 没有偏好时，应该使用 implementations 中排序第一位的算力
        self.assertEqual(result[0]['computing_power'], 5)  # impl_a 的算力
        self.assertEqual(result[0]['default_implementation'], 'impl_a')
        self.assertEqual(result[1]['computing_power'], 7)  # impl_c 的算力
        self.assertEqual(result[1]['default_implementation'], 'impl_c')

    def test_apply_user_preferences_empty_prefs_no_implementations(self):
        """测试空偏好且没有 implementations 时保持原值"""
        from config.unified_config import UnifiedConfigRegistry

        tasks = [
            {'key': 'task1', 'computing_power': 2, 'driver_name': 'GEMINI_IMAGE_EDIT'},
            {'key': 'task2', 'computing_power': 3, 'driver_name': 'GEMINI_IMAGE_EDIT'},
        ]

        result = UnifiedConfigRegistry._apply_user_preferences_to_tasks(tasks, {})

        self.assertEqual(len(result), 2)
        # 没有 implementations 时，保持原值
        self.assertEqual(result[0]['computing_power'], 2)
        self.assertEqual(result[1]['computing_power'], 3)

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_apply_user_preferences_updates_matching_task(self, mock_impl_power_model):
        """测试偏好会更新匹配的任务"""
        from config.unified_config import UnifiedConfigRegistry

        mock_impl_power_model.get_all_powers_for_implementation.return_value = {None: 8}

        tasks = [
            {'key': 'gemini-2.5-flash-image-preview', 'computing_power': 2, 'driver_name': 'GEMINI_IMAGE_EDIT'},
        ]

        user_prefs = {
            'gemini-2.5-flash-image-preview': 'gemini_duomi_v1'
        }

        result = UnifiedConfigRegistry._apply_user_preferences_to_tasks(tasks, user_prefs)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['computing_power'], 8)
        self.assertEqual(result[0]['user_preferred_implementation'], 'gemini_duomi_v1')
        mock_impl_power_model.get_all_powers_for_implementation.assert_called_once_with(
            'gemini_duomi_v1', 'gemini_image_edit'
        )

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_apply_user_preferences_duration_based_power(self, mock_impl_power_model):
        """测试按时长计费的偏好实现方返回字典时取第一个值作为显示算力"""
        from config.unified_config import UnifiedConfigRegistry, UnifiedTaskConfig

        # 注册对应配置，否则 _apply_user_preferences_to_tasks 会跳过
        config = UnifiedTaskConfig(
            id=998,
            key='seedance-task',
            name='Seedance Task',
            category='image_to_video',
            provider='test',
            driver_name='SEEDANCE_TEST'
        )
        UnifiedConfigRegistry.register(config)

        mock_impl_power_model.get_all_powers_for_implementation.return_value = {5: 46, 10: 94}

        tasks = [
            {'key': 'seedance-task', 'computing_power': 2, 'driver_name': 'SEEDANCE_TEST'},
        ]

        user_prefs = {
            'seedance-task': 'seedance_impl'
        }

        result = UnifiedConfigRegistry._apply_user_preferences_to_tasks(tasks, user_prefs)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['computing_power'], 46)
        mock_impl_power_model.get_all_powers_for_implementation.assert_called_once_with(
            'seedance_impl', 'SEEDANCE_TEST'
        )

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_apply_user_preferences_skips_non_matching_pref(self, mock_impl_power_model):
        """测试用户偏好不匹配任何任务时跳过"""
        from config.unified_config import UnifiedConfigRegistry

        tasks = [
            {'key': 'task1', 'computing_power': 2},
        ]

        user_prefs = {
            'nonexistent_task': 'some_impl'
        }

        result = UnifiedConfigRegistry._apply_user_preferences_to_tasks(tasks, user_prefs)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['computing_power'], 2)
        mock_impl_power_model.get_all_powers_for_implementation.assert_not_called()

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_apply_user_preferences_get_power_exception(self, mock_impl_power_model):
        """测试 DB 查询抛出异常时保持原算力"""
        from config.unified_config import UnifiedConfigRegistry

        mock_impl_power_model.get_all_powers_for_implementation.side_effect = Exception("Database error")

        tasks = [
            {'key': 'task1', 'computing_power': 5},
        ]

        # 需要先注册一个配置，否则 task 找不到对应配置
        from config.unified_config import UnifiedTaskConfig
        config = UnifiedTaskConfig(
            id=999,
            key='task1',
            name='Test Task',
            category='image_edit',
            provider='test',
            computing_power=5,
            driver_name='TEST_DRIVER'
        )
        UnifiedConfigRegistry.register(config)

        user_prefs = {
            'task1': 'some_impl'
        }

        result = UnifiedConfigRegistry._apply_user_preferences_to_tasks(tasks, user_prefs)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['computing_power'], 5)

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_apply_user_preferences_db_empty_fallback_to_implementations(self, mock_impl_power_model):
        """测试数据库返回空配置时，从 implementations 列表中获取算力（回退机制）- 防止返回 0"""
        from config.unified_config import UnifiedConfigRegistry, UnifiedTaskConfig

        # Mock 数据库返回空配置
        mock_impl_power_model.get_all_powers_for_implementation.return_value = {}

        # 注册一个任务配置
        config = UnifiedTaskConfig(
            id=997,
            key='grok_image_to_video',
            name='Grok Image to Video',
            category='image_to_video',
            provider='duomi',
            computing_power=0,
            driver_name='grok_image_to_video'
        )
        UnifiedConfigRegistry.register(config)

        tasks = [
            {
                'key': 'grok_image_to_video',
                'computing_power': 0,
                'driver_name': 'grok_image_to_video',
                'implementations': [
                    {'name': 'grok_duomi_v1', 'computing_power': 8, 'sort_order': 100},
                    {'name': 'grok_common_site0_v1', 'computing_power': 8, 'sort_order': 200},
                ]
            },
        ]

        user_prefs = {
            'grok_image_to_video': 'grok_duomi_v1'
        }

        result = UnifiedConfigRegistry._apply_user_preferences_to_tasks(tasks, user_prefs)

        self.assertEqual(len(result), 1)
        # 数据库无配置时，应该从 implementations 列表中获取算力，而不是返回 0
        self.assertEqual(result[0]['computing_power'], 8,
            "数据库无配置时应该从 implementations 获取算力 8，而不是返回 0")
        self.assertEqual(result[0]['user_preferred_implementation'], 'grok_duomi_v1')
        mock_impl_power_model.get_all_powers_for_implementation.assert_called_once_with(
            'grok_duomi_v1', 'grok_image_to_video'
        )

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_apply_user_preferences_no_prefs_computing_power_zero_uses_first_impl(self, mock_impl_power_model):
        """测试没有用户偏好且 computing_power 为 0 时，使用 implementations 第一位的算力 - 防止返回 0"""
        from config.unified_config import UnifiedConfigRegistry

        tasks = [
            {
                'key': 'grok_image_to_video',
                'computing_power': 0,
                'driver_name': 'grok_image_to_video',
                'implementations': [
                    {'name': 'grok_duomi_v1', 'computing_power': 8, 'sort_order': 100},
                    {'name': 'grok_common_site0_v1', 'computing_power': 8, 'sort_order': 200},
                ]
            },
        ]

        result = UnifiedConfigRegistry._apply_user_preferences_to_tasks(tasks, {})

        self.assertEqual(len(result), 1)
        # 没有用户偏好且 computing_power 为 0 时，应该使用 implementations 第一位的算力
        self.assertEqual(result[0]['computing_power'], 8,
            "computing_power 为 0 时应该使用 implementations 第一位的算力 8，而不是保持 0")
        self.assertEqual(result[0]['default_implementation'], 'grok_duomi_v1')
        # 不应该调用数据库查询
        mock_impl_power_model.get_all_powers_for_implementation.assert_not_called()


class TestGetFrontendConfigStructure(unittest.TestCase):
    """前端配置结构测试"""

    def setUp(self):
        """测试前准备"""
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

        from config.unified_config import init_unified_config
        init_unified_config()

    def tearDown(self):
        """测试后清理"""
        from config.unified_config import UnifiedConfigRegistry
        UnifiedConfigRegistry._configs.clear()
        UnifiedConfigRegistry._id_map.clear()
        UnifiedConfigRegistry._implementations.clear()

    def test_tasks_have_required_fields(self):
        """测试任务配置包含必需字段"""
        from config.unified_config import UnifiedConfigRegistry

        config = UnifiedConfigRegistry.get_frontend_config()

        required_fields = ['id', 'key', 'name', 'category', 'computing_power']

        for task in config['tasks'][:5]:  # 检查前5个任务
            for field in required_fields:
                self.assertIn(field, task, f"Task missing required field: {field}")

    def test_categories_have_expected_keys(self):
        """测试分类包含预期的键"""
        from config.unified_config import UnifiedConfigRegistry

        config = UnifiedConfigRegistry.get_frontend_config()

        expected_categories = [
            'image_edit',
            'text_to_video',
            'image_to_video',
            'text_to_image',
            'visual_enhance',
            'audio',
            'digital_human',
        ]

        for cat in expected_categories:
            self.assertIn(cat, config['categories'], f"Missing category: {cat}")

    def test_providers_have_expected_keys(self):
        """测试供应商包含预期的键"""
        from config.unified_config import UnifiedConfigRegistry

        config = UnifiedConfigRegistry.get_frontend_config()

        expected_providers = ['duomi', 'runninghub', 'vidu', 'volcengine', 'local']

        for provider in expected_providers:
            self.assertIn(provider, config['providers'], f"Missing provider: {provider}")


if __name__ == '__main__':
    unittest.main()