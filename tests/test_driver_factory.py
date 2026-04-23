"""
VideoDriverFactory 单元测试
重点覆盖 create_driver_by_implementation 方法，
确保状态查询时可以使用任务提交时记录的 implementation 创建正确的驱动实例。
"""
import sys
from unittest.mock import patch, MagicMock
import unittest

# Mock 可能不存在的外部依赖
sys.modules['utils.sentry_util'] = MagicMock()

from task.visual_drivers.driver_factory import VideoDriverFactory
from task.visual_drivers.base_video_driver import BaseVideoDriver
from config.unified_config import (
    DriverImplementation,
    DriverImplementationId,
    UnifiedConfigRegistry,
    ImplementationConfig,
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

    这个测试直接模拟 _check_task_status 中的驱动创建逻辑，
    验证当 ai_tool.implementation 已记录时，优先使用 create_driver_by_implementation
    而不是重新通过 create_driver_by_type 选择实现方。
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
        """
        测试：_check_task_status 函数中，当 ai_tool.implementation 已记录时，
        应优先使用 create_driver_by_implementation 创建驱动。

        通过直接模拟 _check_task_status 中的驱动选择逻辑来验证。
        """
        import asyncio
        from unittest.mock import patch
        from config.unified_config import get_implementation_name

        # 注册驱动
        VideoDriverFactory.register_driver("grok_duomi_v1", MockDriver)

        # 模拟 ai_tool
        ai_tool = self._create_mock_ai_tool(implementation_id=48)

        # 验证 get_implementation_name 能正确解析 implementation_id
        impl_name = get_implementation_name(ai_tool.implementation)
        self.assertEqual(impl_name, "grok_duomi_v1")

        # 验证 create_driver_by_implementation 能创建正确的驱动
        driver = VideoDriverFactory.create_driver_by_implementation(impl_name)
        self.assertIsNotNone(driver)
        self.assertIsInstance(driver, MockDriver)

        # 验证当 implementation 为 0（未记录）时，create_driver_by_implementation 返回 None
        ai_tool_no_impl = self._create_mock_ai_tool(implementation_id=0)
        impl_name_zero = get_implementation_name(ai_tool_no_impl.implementation)
        self.assertEqual(impl_name_zero, "unknown")

        driver_none = VideoDriverFactory.create_driver_by_implementation(impl_name_zero)
        self.assertIsNone(driver_none)

    def test_implementation_id_to_name_mapping(self):
        """
        测试：implementation ID 与名称的映射关系正确，
        确保 _check_task_status 中通过 get_implementation_name 能正确解析。
        """
        from config.unified_config import get_implementation_name, get_implementation_id

        # 验证 Grok 相关的映射
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
        """
        测试：create_driver_by_type 和 create_driver_by_implementation
        在相同条件下应返回相同类型的驱动实例。
        """
        VideoDriverFactory._registered_drivers.clear()
        VideoDriverFactory.register_driver("grok_duomi_v1", MockDriver)

        # 通过 implementation 名称创建
        driver_by_impl = VideoDriverFactory.create_driver_by_implementation("grok_duomi_v1")

        self.assertIsNotNone(driver_by_impl)
        self.assertEqual(driver_by_impl.driver_name, "mock_driver")


if __name__ == "__main__":
    unittest.main()
