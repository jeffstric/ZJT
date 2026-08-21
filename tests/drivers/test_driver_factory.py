"""
VideoDriverFactory 单元测试
重点覆盖 create_driver_by_implementation 方法，
确保状态查询时可以使用任务提交时记录的 implementation 创建正确的驱动实例。

同时覆盖：
- get_driver_availability: 验证遍历所有实现方，任意一个可用即标记 available
- _is_driver_available: 验证驱动配置检查
- _get_implementation_for_user: 验证跳过不可用实现方
"""
import sys
from unittest.mock import patch, MagicMock
import unittest

# Mock 可能不存在的外部依赖
_saved_sentry = sys.modules.get('utils.sentry_util')
sys.modules['utils.sentry_util'] = MagicMock()

from task.visual_drivers.driver_factory import VideoDriverFactory
from task.visual_drivers.base_video_driver import BaseVideoDriver
from task.visual_drivers.exceptions import DriverConfigError
from config.unified_config import (
    DriverImplementation,
    DriverImplementationId,
    UnifiedConfigRegistry,
    UnifiedTaskConfig,
    ImplementationConfig,
    TaskCategory,
    TaskProvider,
)


class MockDriver(BaseVideoDriver):
    """测试用的模拟驱动"""

    def __init__(self, **kwargs):
        super().__init__(driver_name="mock_driver", driver_type=999)
        self.extra_params = kwargs

    def build_create_request(self, ai_tool):
        return {}

    def build_check_query(self, project_id):
        return {}

    def submit_task(self, ai_tool):
        return {"success": True, "project_id": "mock_123"}

    def check_status(self, project_id):
        return {"status": "RUNNING"}


class MockDriverWithParams(BaseVideoDriver):
    """带参数的测试驱动"""

    def __init__(self, site_id=None, **kwargs):
        super().__init__(driver_name=f"mock_driver_{site_id}", driver_type=999)
        self.site_id = site_id

    def build_create_request(self, ai_tool):
        return {}

    def build_check_query(self, project_id):
        return {}

    def submit_task(self, ai_tool):
        return {"success": True, "project_id": "mock_123"}

    def check_status(self, project_id):
        return {"status": "RUNNING"}


class MockConfigMissingDriver(BaseVideoDriver):
    """模拟密钥未配置的驱动"""

    def __init__(self, **kwargs):
        super().__init__(driver_name="config_missing_driver", driver_type=999)
        self._validate_required({"Test API Key": ""})

    def build_create_request(self, ai_tool): return {}
    def build_check_query(self, project_id): return {}
    def submit_task(self, ai_tool): return {}
    def check_status(self, project_id): return {}


class TestCreateDriverByImplementation(unittest.TestCase):
    """测试 create_driver_by_implementation 方法"""

    def setUp(self):
        """每个测试前清理已注册驱动"""
        VideoDriverFactory._registered_drivers.clear()
        VideoDriverFactory._last_create_error = None

    def tearDown(self):
        """每个测试后清理"""
        VideoDriverFactory._registered_drivers.clear()
        VideoDriverFactory._last_create_error = None

    def test_create_driver_by_implementation_success(self):
        """测试：根据已注册的 implementation 名称成功创建驱动"""
        VideoDriverFactory.register_driver("mock_impl_v1", MockDriver)

        driver = VideoDriverFactory.create_driver_by_implementation("mock_impl_v1")

        self.assertIsNotNone(driver)
        self.assertIsInstance(driver, MockDriver)
        self.assertEqual(driver.driver_name, "mock_driver")

    def test_create_driver_by_implementation_with_params(self):
        """测试：根据 implementation 名称创建驱动时正确传递 driver_params"""
        # 注册实现方配置（带 driver_params）
        impl_config = ImplementationConfig(
            name="mock_impl_with_params",
            display_name="Mock With Params",
            driver_class="MockDriverWithParams",
            driver_params={"site_id": "site_1"},
        )
        UnifiedConfigRegistry.register_implementation(impl_config)

        VideoDriverFactory.register_driver("mock_impl_with_params", MockDriverWithParams)

        driver = VideoDriverFactory.create_driver_by_implementation("mock_impl_with_params")

        self.assertIsNotNone(driver)
        self.assertIsInstance(driver, MockDriverWithParams)
        self.assertEqual(driver.site_id, "site_1")

    def test_create_driver_by_implementation_not_registered(self):
        """测试：未注册的 implementation 返回 None 并记录错误"""
        driver = VideoDriverFactory.create_driver_by_implementation("not_exist_impl")

        self.assertIsNone(driver)
        error = VideoDriverFactory.get_last_create_error()
        self.assertIsNotNone(error)
        self.assertEqual(error["reason"], "NOT_REGISTERED")
        self.assertIn("not_exist_impl", error["message"])

    def test_create_driver_by_implementation_config_missing(self):
        """测试：驱动配置不完整时返回 None 并记录 CONFIG_MISSING 错误"""
        class DriverWithRequiredConfig(BaseVideoDriver):
            def __init__(self):
                super().__init__(driver_name="config_test", driver_type=999)
                self._validate_required({"Missing Key": ""})

            def build_create_request(self, ai_tool): return {}
            def build_check_query(self, project_id): return {}
            def submit_task(self, ai_tool): return {}
            def check_status(self, project_id): return {}

        VideoDriverFactory.register_driver("config_missing_impl", DriverWithRequiredConfig)

        driver = VideoDriverFactory.create_driver_by_implementation("config_missing_impl")

        self.assertIsNone(driver)
        error = VideoDriverFactory.get_last_create_error()
        self.assertIsNotNone(error)
        self.assertEqual(error["reason"], "CONFIG_MISSING")


class TestStatusCheckUsesRecordedImplementation(unittest.TestCase):
    """
    测试状态查询时使用记录的 implementation 的逻辑。
    """

    def setUp(self):
        VideoDriverFactory._registered_drivers.clear()

    def tearDown(self):
        VideoDriverFactory._registered_drivers.clear()

    def _create_mock_ai_tool(self, implementation_id=0):
        """创建模拟的 ai_tool 对象"""
        tool = MagicMock()
        tool.id = 12345
        tool.type = 27  # GROK_IMAGE_TO_VIDEO
        tool.project_id = "test_project_123"
        tool.user_id = 1001
        tool.implementation = implementation_id
        return tool

    def test_check_status_logic_prefers_recorded_implementation(self):
        """测试：当 ai_tool.implementation 已记录时，应优先使用 create_driver_by_implementation"""
        import asyncio
        from unittest.mock import patch
        from config.unified_config import get_implementation_name

        VideoDriverFactory.register_driver("grok_duomi_v1", MockDriver)

        ai_tool = self._create_mock_ai_tool(implementation_id=48)

        impl_name = get_implementation_name(ai_tool.implementation)
        self.assertEqual(impl_name, "grok_duomi_v1")

        driver = VideoDriverFactory.create_driver_by_implementation(impl_name)
        self.assertIsNotNone(driver)
        self.assertIsInstance(driver, MockDriver)

        ai_tool_no_impl = self._create_mock_ai_tool(implementation_id=0)
        impl_name_zero = get_implementation_name(ai_tool_no_impl.implementation)
        self.assertEqual(impl_name_zero, "unknown")

        driver_none = VideoDriverFactory.create_driver_by_implementation(impl_name_zero)
        self.assertIsNone(driver_none)

    def test_implementation_id_to_name_mapping(self):
        """测试：implementation ID 与名称的映射关系正确"""
        from config.unified_config import get_implementation_name, get_implementation_id

        self.assertEqual(get_implementation_name(48), "grok_duomi_v1")
        self.assertEqual(get_implementation_id("grok_duomi_v1"), 48)

        self.assertEqual(get_implementation_name(42), "grok_common_site0_v1")
        self.assertEqual(get_implementation_id("grok_common_site0_v1"), 42)


class TestDriverSelectionConsistency(unittest.TestCase):
    """
    测试驱动选择的一致性：
    任务提交和状态查询应能选择相同的实现方。
    """

    def test_create_driver_by_type_vs_implementation(self):
        """测试：create_driver_by_type 和 create_driver_by_implementation 一致性"""
        VideoDriverFactory._registered_drivers.clear()
        VideoDriverFactory.register_driver("grok_duomi_v1", MockDriver)

        driver_by_impl = VideoDriverFactory.create_driver_by_implementation("grok_duomi_v1")

        self.assertIsNotNone(driver_by_impl)
        self.assertEqual(driver_by_impl.driver_name, "mock_driver")


# ==================== 新增：驱动可用性检查测试 ====================

class TestIsDriverAvailable(unittest.TestCase):
    """测试 _is_driver_available 方法"""

    def setUp(self):
        VideoDriverFactory._registered_drivers.clear()

    def tearDown(self):
        VideoDriverFactory._registered_drivers.clear()

    def test_available_driver_returns_true(self):
        """密钥已配置的驱动应返回 True"""
        VideoDriverFactory.register_driver("mock_ok", MockDriver)
        self.assertTrue(VideoDriverFactory._is_driver_available("mock_ok"))

    def test_config_missing_driver_returns_false(self):
        """密钥未配置的驱动应返回 False"""
        VideoDriverFactory.register_driver("mock_missing", MockConfigMissingDriver)
        self.assertFalse(VideoDriverFactory._is_driver_available("mock_missing"))

    def test_unregistered_driver_returns_false(self):
        """未注册的驱动应返回 False"""
        self.assertFalse(VideoDriverFactory._is_driver_available("not_registered_at_all"))

    def test_driver_init_exception_returns_false(self):
        """初始化抛异常的驱动应返回 False"""
        class BrokenDriver(BaseVideoDriver):
            def __init__(self):
                raise RuntimeError("something broke")

            def build_create_request(self, ai_tool): return {}
            def build_check_query(self, project_id): return {}
            def submit_task(self, ai_tool): return {}
            def check_status(self, project_id): return {}

        VideoDriverFactory.register_driver("broken_driver", BrokenDriver)
        self.assertFalse(VideoDriverFactory._is_driver_available("broken_driver"))


class TestGetDriverAvailabilityChecksAllImplementations(unittest.TestCase):
    """
    测试 get_driver_availability 遍历所有实现方。
    如果恢复为只检查默认实现方，以下测试将失败。
    """

    TASK_TYPE_ID = 9001  # 使用不冲突的测试 ID

    def _register_test_task(self, default_impl, alt_impls):
        """
        注册一个测试任务配置，包含默认实现方和可选实现方。
        """
        config = UnifiedTaskConfig(
            id=self.TASK_TYPE_ID,
            key='test_availability_task',
            name='Test Availability Task',
            category=TaskCategory.IMAGE_EDIT,
            provider=TaskProvider.DUOMI,
            driver_name='test_driver_key',
            implementation=default_impl,
            implementations=[default_impl] + alt_impls,
            computing_power=1,
        )
        # 直接添加到 registry（绕过正常的 register 流程）
        UnifiedConfigRegistry._configs[config.key] = config
        UnifiedConfigRegistry._id_map[config.id] = config.key
        return config

    def setUp(self):
        VideoDriverFactory._registered_drivers.clear()
        # 保存原始 configs 以便恢复
        self._original_configs = UnifiedConfigRegistry._configs.copy()
        self._original_id_map = UnifiedConfigRegistry._id_map.copy()

    def tearDown(self):
        VideoDriverFactory._registered_drivers.clear()
        # 恢复原始 configs
        UnifiedConfigRegistry._configs = self._original_configs
        UnifiedConfigRegistry._id_map = self._original_id_map

    def test_default_unavailable_alt_available_marks_available(self):
        """
        默认实现方不可用，但可选实现方可用 → 应标记 available: true

        这是核心回归测试：如果恢复为只检查默认实现方的旧代码，此测试将失败。
        """
        # 注册：默认实现方（密钥缺失）+ 可选实现方（正常）
        VideoDriverFactory.register_driver("test_default_missing", MockConfigMissingDriver)
        VideoDriverFactory.register_driver("test_alt_ok", MockDriver)

        self._register_test_task("test_default_missing", ["test_alt_ok"])

        result = VideoDriverFactory.get_driver_availability()

        self.assertEqual(result[str(self.TASK_TYPE_ID)]["available"], True)
        self.assertEqual(result[str(self.TASK_TYPE_ID)]["missing_configs"], [])

    def test_all_implementations_unavailable_marks_unavailable(self):
        """
        所有实现方都不可用 → 应标记 available: false
        """
        VideoDriverFactory.register_driver("test_missing_a", MockConfigMissingDriver)
        VideoDriverFactory.register_driver("test_missing_b", MockConfigMissingDriver)

        self._register_test_task("test_missing_a", ["test_missing_b"])

        result = VideoDriverFactory.get_driver_availability()

        self.assertEqual(result[str(self.TASK_TYPE_ID)]["available"], False)
        self.assertIn("Test API Key", result[str(self.TASK_TYPE_ID)]["missing_configs"])

    def test_default_available_marks_available(self):
        """
        默认实现方可用 → 应标记 available: true
        """
        VideoDriverFactory.register_driver("test_default_ok", MockDriver)

        self._register_test_task("test_default_ok", [])

        result = VideoDriverFactory.get_driver_availability()

        self.assertEqual(result[str(self.TASK_TYPE_ID)]["available"], True)

    def test_unregistered_impl_skipped_gracefully(self):
        """
        实现方未注册 → 跳过，继续检查下一个
        """
        VideoDriverFactory.register_driver("test_registered_ok", MockDriver)
        # "test_not_registered" 不注册

        self._register_test_task("test_not_registered", ["test_registered_ok"])

        result = VideoDriverFactory.get_driver_availability()

        # 未注册的被跳过，注册且可用的是第二个 → available: true
        self.assertEqual(result[str(self.TASK_TYPE_ID)]["available"], True)


class TestGetImplementationForUserSkipsUnavailable(unittest.TestCase):
    """
    测试 _get_implementation_for_user 跳过不可用的实现方。
    如果恢复为不检查可用性的旧代码，以下测试将失败。
    """

    TASK_TYPE_ID = 9002

    def _register_test_task(self, impls_with_order):
        """
        注册测试任务和实现方。
        impls_with_order: [(impl_name, driver_class, sort_order), ...]
        """
        impl_names = []
        for impl_name, driver_class, sort_order in impls_with_order:
            VideoDriverFactory.register_driver(impl_name, driver_class)
            impl_config = ImplementationConfig(
                name=impl_name,
                display_name=impl_name,
                driver_class=impl_name,
                sort_order=sort_order,
            )
            UnifiedConfigRegistry.register_implementation(impl_config)
            impl_names.append(impl_name)

        config = UnifiedTaskConfig(
            id=self.TASK_TYPE_ID,
            key='test_impl_selection_task',
            name='Test Impl Selection',
            category=TaskCategory.IMAGE_EDIT,
            provider=TaskProvider.DUOMI,
            driver_name='test_impl_driver_key',
            implementation=impl_names[0] if impl_names else None,
            implementations=impl_names,
            computing_power=1,
        )
        UnifiedConfigRegistry._configs[config.key] = config
        UnifiedConfigRegistry._id_map[config.id] = config.key
        return config

    def setUp(self):
        VideoDriverFactory._registered_drivers.clear()
        VideoDriverFactory._last_create_error = None
        self._original_configs = UnifiedConfigRegistry._configs.copy()
        self._original_id_map = UnifiedConfigRegistry._id_map.copy()
        self._original_implementations = UnifiedConfigRegistry._implementations.copy()

    def tearDown(self):
        VideoDriverFactory._registered_drivers.clear()
        VideoDriverFactory._last_create_error = None
        UnifiedConfigRegistry._configs = self._original_configs
        UnifiedConfigRegistry._id_map = self._original_id_map
        UnifiedConfigRegistry._implementations = self._original_implementations

    def test_skips_unavailable_default_selects_available_alt(self):
        """
        默认实现方密钥缺失，排序靠前的不可用 → 应自动选择可用的实现方。

        核心回归测试：恢复旧代码会导致选择不可用的默认实现方。
        """
        # 排序低的不可用（默认），排序高的可用
        config = self._register_test_task([
            ("test_missing_default", MockConfigMissingDriver, 100),  # sort_order=100, 优先但不可用
            ("test_ok_alt", MockDriver, 200),  # sort_order=200, 可用
        ])

        impl_name, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=None, config=config
        )

        self.assertEqual(impl_name, "test_ok_alt")

    def test_all_unavailable_falls_back_to_default(self):
        """
        所有实现方都不可用 → 回退到默认实现方（至少有值）
        """
        config = self._register_test_task([
            ("test_all_missing_a", MockConfigMissingDriver, 100),
            ("test_all_missing_b", MockConfigMissingDriver, 200),
        ])

        impl_name, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=None, config=config
        )

        # 回退到 implementation 字段（第一个）
        self.assertEqual(impl_name, "test_all_missing_a")

    def test_default_available_selected_directly(self):
        """
        默认实现方可用 → 直接选择
        """
        config = self._register_test_task([
            ("test_ok_default", MockDriver, 100),
            ("test_ok_alt", MockDriver, 200),
        ])

        impl_name, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=None, config=config
        )

        self.assertEqual(impl_name, "test_ok_default")

    @patch('model.users.UsersModel')
    def test_user_preference_unavailable_falls_back(self, MockUsersModel):
        """
        用户偏好的实现方不可用 → 自动降级选择可用的实现方

        核心回归测试：恢复旧代码会使用不可用的用户偏好。
        """
        MockUsersModel.get_implementation_preference.return_value = "test_missing_pref"
        MockUsersModel.is_implementation_locked.return_value = False

        config = self._register_test_task([
            ("test_missing_pref", MockConfigMissingDriver, 100),  # 用户偏好但不可用
            ("test_ok_fallback", MockDriver, 200),
        ])

        impl_name, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=1, config=config
        )

        # 用户偏好不可用，应降级选择可用的
        self.assertEqual(impl_name, "test_ok_fallback")

    @patch('model.users.UsersModel')
    def test_locked_preference_available_is_used(self, MockUsersModel):
        MockUsersModel.get_implementation_preference.return_value = "test_ok_locked"
        MockUsersModel.is_implementation_locked.return_value = True

        config = self._register_test_task([
            ("test_ok_locked", MockDriver, 200),
            ("test_ok_other", MockDriver, 100),
        ])

        impl_name, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=1, config=config
        )
        self.assertEqual(impl_name, "test_ok_locked")

    @patch('model.users.UsersModel')
    def test_locked_preference_unavailable_does_not_fallback(self, MockUsersModel):
        from config.constant import DRIVER_ERROR_FIXED_IMPLEMENTATION_UNAVAILABLE

        MockUsersModel.get_implementation_preference.return_value = "test_missing_locked"
        MockUsersModel.is_implementation_locked.return_value = True

        config = self._register_test_task([
            ("test_missing_locked", MockConfigMissingDriver, 100),
            ("test_ok_fallback", MockDriver, 200),
        ])

        impl_name, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=1, config=config
        )
        self.assertIsNone(impl_name)
        error = VideoDriverFactory.get_last_create_error()
        self.assertIsNotNone(error)
        self.assertEqual(error["reason"], DRIVER_ERROR_FIXED_IMPLEMENTATION_UNAVAILABLE)

    @patch('model.users.UsersModel')
    def test_create_driver_keeps_locked_unavailable_error(self, MockUsersModel):
        from config.constant import DRIVER_ERROR_FIXED_IMPLEMENTATION_UNAVAILABLE

        MockUsersModel.get_implementation_preference.return_value = "test_missing_locked"
        MockUsersModel.is_implementation_locked.return_value = True

        self._register_test_task([
            ("test_missing_locked", MockConfigMissingDriver, 100),
            ("test_ok_fallback", MockDriver, 200),
        ])

        driver = VideoDriverFactory.create_driver_by_type(self.TASK_TYPE_ID, user_id=1)
        self.assertIsNone(driver)
        error = VideoDriverFactory.get_last_create_error()
        self.assertEqual(error["reason"], DRIVER_ERROR_FIXED_IMPLEMENTATION_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()


# ==================== 新增：get_agent_hint_for_task 测试 ====================

class TestGetAgentHintForTask(unittest.TestCase):
    """测试 VideoDriverFactory.get_agent_hint_for_task()"""

    TASK_TYPE_ID = 9010

    def setUp(self):
        VideoDriverFactory._registered_drivers.clear()
        VideoDriverFactory._last_create_error = None
        self._original_configs = UnifiedConfigRegistry._configs.copy()
        self._original_id_map = UnifiedConfigRegistry._id_map.copy()
        self._original_implementations = UnifiedConfigRegistry._implementations.copy()

    def tearDown(self):
        VideoDriverFactory._registered_drivers.clear()
        VideoDriverFactory._last_create_error = None
        UnifiedConfigRegistry._configs = self._original_configs
        UnifiedConfigRegistry._id_map = self._original_id_map
        UnifiedConfigRegistry._implementations = self._original_implementations

    def test_no_config_returns_none(self):
        """无任务配置返回 None"""
        result = VideoDriverFactory.get_agent_hint_for_task(99999)
        self.assertIsNone(result)

    def test_no_impl_name_returns_none(self):
        """无实现方名称返回 None"""
        config = UnifiedTaskConfig(
            id=self.TASK_TYPE_ID,
            key='test_hint_no_impl',
            name='Test Hint No Impl',
            category=TaskCategory.IMAGE_EDIT,
            provider=TaskProvider.DUOMI,
            driver_name='test_hint_driver',
            implementation=None,
            implementations=[],
            computing_power=1,
        )
        UnifiedConfigRegistry._configs[config.key] = config
        UnifiedConfigRegistry._id_map[config.id] = config.key

        result = VideoDriverFactory.get_agent_hint_for_task(self.TASK_TYPE_ID)
        self.assertIsNone(result)

    def test_unregistered_driver_returns_none(self):
        """未注册的驱动返回 None"""
        impl_config = ImplementationConfig(
            name="test_hint_unregistered",
            display_name="Test Hint",
            driver_class="SomeDriver",
        )
        UnifiedConfigRegistry.register_implementation(impl_config)

        config = UnifiedTaskConfig(
            id=self.TASK_TYPE_ID,
            key='test_hint_unreg',
            name='Test Hint Unreg',
            category=TaskCategory.IMAGE_EDIT,
            provider=TaskProvider.DUOMI,
            driver_name='test_hint_driver',
            implementation='test_hint_unregistered',
            implementations=['test_hint_unregistered'],
            computing_power=1,
        )
        UnifiedConfigRegistry._configs[config.key] = config
        UnifiedConfigRegistry._id_map[config.id] = config.key

        result = VideoDriverFactory.get_agent_hint_for_task(self.TASK_TYPE_ID)
        self.assertIsNone(result)

    def test_driver_with_hint_returns_dict(self):
        """有 agent_hint 的驱动返回完整 dict"""
        class HintDriver(BaseVideoDriver):
            agent_hint = "这是一个测试提示"

            def __init__(self, **kwargs):
                super().__init__(driver_name="hint_driver", driver_type=999)

            def build_create_request(self, ai_tool): return {}
            def build_check_query(self, project_id): return {}
            def submit_task(self, ai_tool): return {}
            def check_status(self, project_id): return {}

        impl_config = ImplementationConfig(
            name="test_hint_impl",
            display_name="测试实现方",
            driver_class="HintDriver",
        )
        UnifiedConfigRegistry.register_implementation(impl_config)
        VideoDriverFactory.register_driver("test_hint_impl", HintDriver)

        config = UnifiedTaskConfig(
            id=self.TASK_TYPE_ID,
            key='test_hint_ok',
            name='Test Hint OK',
            category=TaskCategory.IMAGE_EDIT,
            provider=TaskProvider.DUOMI,
            driver_name='test_hint_driver',
            implementation='test_hint_impl',
            implementations=['test_hint_impl'],
            computing_power=1,
        )
        UnifiedConfigRegistry._configs[config.key] = config
        UnifiedConfigRegistry._id_map[config.id] = config.key

        result = VideoDriverFactory.get_agent_hint_for_task(self.TASK_TYPE_ID)

        self.assertIsNotNone(result)
        self.assertEqual(result['impl_name'], 'test_hint_impl')
        self.assertEqual(result['display_name'], '测试实现方')
        self.assertEqual(result['hint'], '这是一个测试提示')

    def test_driver_without_hint_returns_none(self):
        """没有 agent_hint 的驱动返回 None"""
        VideoDriverFactory.register_driver("test_no_hint", MockDriver)

        impl_config = ImplementationConfig(
            name="test_no_hint",
            display_name="No Hint",
            driver_class="MockDriver",
        )
        UnifiedConfigRegistry.register_implementation(impl_config)

        config = UnifiedTaskConfig(
            id=self.TASK_TYPE_ID,
            key='test_no_hint_task',
            name='Test No Hint',
            category=TaskCategory.IMAGE_EDIT,
            provider=TaskProvider.DUOMI,
            driver_name='test_no_hint_driver',
            implementation='test_no_hint',
            implementations=['test_no_hint'],
            computing_power=1,
        )
        UnifiedConfigRegistry._configs[config.key] = config
        UnifiedConfigRegistry._id_map[config.id] = config.key

        result = VideoDriverFactory.get_agent_hint_for_task(self.TASK_TYPE_ID)
        self.assertIsNone(result)


# ==================== 新增：_get_display_name_for_impl 测试 ====================

class TestGetDisplayNameForImpl(unittest.TestCase):
    """测试 VideoDriverFactory._get_display_name_for_impl()"""

    def setUp(self):
        self._original_implementations = UnifiedConfigRegistry._implementations.copy()

    def tearDown(self):
        UnifiedConfigRegistry._implementations = self._original_implementations

    def test_with_display_name(self):
        """有 display_name 时返回配置的名称"""
        impl_config = ImplementationConfig(
            name="test_display_impl",
            display_name="友好的显示名",
            driver_class="SomeDriver",
        )
        UnifiedConfigRegistry.register_implementation(impl_config)

        result = VideoDriverFactory._get_display_name_for_impl("test_display_impl")
        self.assertEqual(result, "友好的显示名")

    def test_without_display_name_fallback(self):
        """无 display_name 时返回 impl_name"""
        result = VideoDriverFactory._get_display_name_for_impl("nonexistent_impl_xyz")
        self.assertEqual(result, "nonexistent_impl_xyz")


# ==================== 新增：get_implementation_for_user (公开方法) 测试 ====================

class TestGetImplementationForUserPublic(unittest.TestCase):
    """测试 VideoDriverFactory.get_implementation_for_user() 公开方法"""

    TASK_TYPE_ID = 9011

    def setUp(self):
        VideoDriverFactory._registered_drivers.clear()
        self._original_configs = UnifiedConfigRegistry._configs.copy()
        self._original_id_map = UnifiedConfigRegistry._id_map.copy()
        self._original_implementations = UnifiedConfigRegistry._implementations.copy()

    def tearDown(self):
        VideoDriverFactory._registered_drivers.clear()
        UnifiedConfigRegistry._configs = self._original_configs
        UnifiedConfigRegistry._id_map = self._original_id_map
        UnifiedConfigRegistry._implementations = self._original_implementations

    def test_no_config_returns_none(self):
        """无任务配置返回 None"""
        result = VideoDriverFactory.get_implementation_for_user(99999)
        self.assertIsNone(result)

    def test_returns_impl_name(self):
        """返回实现方名称"""
        VideoDriverFactory.register_driver("test_pub_impl", MockDriver)

        impl_config = ImplementationConfig(
            name="test_pub_impl",
            display_name="Test Pub",
            driver_class="MockDriver",
            sort_order=100,
        )
        UnifiedConfigRegistry.register_implementation(impl_config)

        config = UnifiedTaskConfig(
            id=self.TASK_TYPE_ID,
            key='test_pub_task',
            name='Test Pub Task',
            category=TaskCategory.IMAGE_EDIT,
            provider=TaskProvider.DUOMI,
            driver_name='test_pub_driver',
            implementation='test_pub_impl',
            implementations=['test_pub_impl'],
            computing_power=1,
        )
        UnifiedConfigRegistry._configs[config.key] = config
        UnifiedConfigRegistry._id_map[config.id] = config.key

        result = VideoDriverFactory.get_implementation_for_user(self.TASK_TYPE_ID)
        self.assertEqual(result, "test_pub_impl")


# 恢复 sys.modules
if _saved_sentry is not None:
    sys.modules['utils.sentry_util'] = _saved_sentry
else:
    sys.modules.pop('utils.sentry_util', None)
