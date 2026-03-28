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

    def test_get_frontend_config_without_user_prefs_uses_first_impl_power(self):
        """测试无用户偏好时使用 implementations 排序第一位的算力"""
        from config.unified_config import UnifiedConfigRegistry

        config = UnifiedConfigRegistry.get_frontend_config()

        # 找到 gemini-2.5-flash-image-preview 任务
        for task in config['tasks']:
            if task.get('key') == 'gemini-2.5-flash-image-preview':
                impls = task.get('implementations', [])
                if impls:
                    # implementations 按 sort_order 排序，第一位应该是 sort_order 最小的
                    first_impl = impls[0]
                    # 验证 task.computing_power 等于第一位 implementations 的 computing_power
                    self.assertEqual(task.get('computing_power'), first_impl.get('computing_power'))
                    self.assertEqual(task.get('default_implementation'), first_impl.get('name'))
                break


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

        mock_impl_power_model.get_power.return_value = 8

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
        mock_impl_power_model.get_power.assert_called_once_with('gemini_duomi_v1', 'gemini_image_edit')

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
        mock_impl_power_model.get_power.assert_not_called()

    @patch('model.implementation_power.ImplementationPowerModel')
    def test_apply_user_preferences_get_power_exception(self, mock_impl_power_model):
        """测试 get_power 抛出异常时保持原算力"""
        from config.unified_config import UnifiedConfigRegistry

        mock_impl_power_model.get_power.side_effect = Exception("Database error")

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
