"""带参考视频时跳过吃不下视频的实现方；固定供应商不因输入不兼容被清掉。"""
import asyncio
import logging
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from config.constant import (
    DRIVER_ERROR_FIXED_IMPLEMENTATION_INPUT_INCOMPATIBLE,
    DRIVER_ERROR_INPUT_INCOMPATIBLE,
)
from config.unified_config import (
    ImplementationConfig,
    TaskCategory,
    TaskProvider,
    UnifiedConfigRegistry,
    UnifiedTaskConfig,
)
from task.visual_drivers.driver_factory import VideoDriverFactory
from task.visual_drivers.exceptions import UnsupportedReferenceVideoError
from task.visual_drivers.minimax_h3_keyframe_ref_runninghub_v1_driver import (
    MinimaxH3KeyframeRefRunninghubV1Driver,
)
from task.visual_drivers.minimax_h3_reference_runninghub_v1_driver import (
    MinimaxH3ReferenceRunninghubV1Driver,
)
from tests.drivers.test_driver_factory import MockDriver


class _KfrBare(MinimaxH3KeyframeRefRunninghubV1Driver):
    def __init__(self):
        self.logger = logging.getLogger("kfr-ref-video-test")
        self.uploaded = []

    async def _upload_image_to_runninghub(self, image_url, description):
        self.uploaded.append(image_url)
        return "uploaded"


class _ParentRejectsVideo(MinimaxH3ReferenceRunninghubV1Driver):
    def __init__(self):
        self.logger = logging.getLogger("h3-ref-video-test")

    async def build_create_request(self, ai_tool):
        raise UnsupportedReferenceVideoError("首帧参考混合模型不支持参考视频")


class RejectVideoDriver(MockDriver):
    def validate_input_compatibility(self, ai_tool):
        if getattr(ai_tool, "video_path", None):
            return False, "不支持参考视频"
        return True, None


class BoomValidateDriver(MockDriver):
    def validate_input_compatibility(self, ai_tool):
        raise RuntimeError("probe boom")


class TestKfrRejectsReferenceVideo(unittest.TestCase):
    def test_validate_false_when_video_present(self):
        driver = _KfrBare()
        ok, reason = driver.validate_input_compatibility(
            SimpleNamespace(video_path="/upload/ref.mp4"),
        )
        self.assertFalse(ok)
        self.assertIn("参考视频", reason)

    def test_validate_true_without_video(self):
        driver = _KfrBare()
        ok, reason = driver.validate_input_compatibility(SimpleNamespace(video_path=""))
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_build_create_request_raises_before_upload(self):
        driver = _KfrBare()
        tool = SimpleNamespace(
            video_path="/upload/ref.mp4",
            prompt="一只猫",
            reference_images="[]",
        )
        with self.assertRaises(UnsupportedReferenceVideoError):
            asyncio.run(driver.build_create_request(tool))
        self.assertEqual(driver.uploaded, [])

    def test_parent_submit_returns_user_error_without_retry(self):
        driver = _ParentRejectsVideo()
        result = asyncio.run(driver.submit_task(SimpleNamespace(prompt="一只猫", duration=5, id=1)))
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "USER")
        self.assertFalse(result["retry"])
        self.assertNotIn("服务异常", result["error"])
        self.assertIn("参考视频", result["error"])


class TestReferenceVideoSelection(unittest.TestCase):
    TASK_TYPE_ID = 9022

    def _register(self, impls_with_order):
        impl_names = []
        for impl_name, driver_class, sort_order in impls_with_order:
            VideoDriverFactory.register_driver(impl_name, driver_class)
            UnifiedConfigRegistry.register_implementation(ImplementationConfig(
                name=impl_name,
                display_name=impl_name,
                driver_class=impl_name,
                sort_order=sort_order,
            ))
            impl_names.append(impl_name)
        config = UnifiedTaskConfig(
            id=self.TASK_TYPE_ID,
            key="test_ref_video_selection_9022",
            name="Test Ref Video Selection",
            category=TaskCategory.IMAGE_EDIT,
            provider=TaskProvider.DUOMI,
            driver_name="test_ref_video_driver_key",
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

    def test_without_tool_keeps_sort_first(self):
        self._register([
            ("reject_video_9022", RejectVideoDriver, 100),
            ("accept_video_9022", MockDriver, 200),
        ])
        name, error = VideoDriverFactory.resolve_implementation_for_user(self.TASK_TYPE_ID)
        self.assertEqual(name, "reject_video_9022")
        self.assertIsNone(error)
        self.assertIsNone(VideoDriverFactory.get_last_create_error())

    def test_with_video_skips_incompatible_first(self):
        self._register([
            ("reject_video_9022", RejectVideoDriver, 100),
            ("accept_video_9022", MockDriver, 200),
        ])
        tool = SimpleNamespace(video_path="/upload/ref.mp4")
        name, error = VideoDriverFactory.resolve_implementation_for_user(
            self.TASK_TYPE_ID, compatibility_tool=tool,
        )
        self.assertEqual(name, "accept_video_9022")
        self.assertIsNone(error)

    def test_probe_exception_skips_candidate(self):
        self._register([
            ("boom_video_9022", BoomValidateDriver, 100),
            ("accept_video_9022", MockDriver, 200),
        ])
        tool = SimpleNamespace(video_path="/upload/ref.mp4")
        name, error = VideoDriverFactory.resolve_implementation_for_user(
            self.TASK_TYPE_ID, compatibility_tool=tool,
        )
        self.assertEqual(name, "accept_video_9022")
        self.assertIsNone(error)

    def test_all_incompatible_returns_first_reason(self):
        self._register([
            ("reject_video_9022", RejectVideoDriver, 100),
            ("reject_video_b_9022", RejectVideoDriver, 200),
        ])
        tool = SimpleNamespace(video_path="/upload/ref.mp4")
        name, error = VideoDriverFactory.resolve_implementation_for_user(
            self.TASK_TYPE_ID, compatibility_tool=tool,
        )
        self.assertIsNone(name)
        self.assertEqual(error["reason"], DRIVER_ERROR_INPUT_INCOMPATIBLE)
        self.assertIn("不支持参考视频", error["message"])
        self.assertEqual(VideoDriverFactory.get_last_create_error()["reason"], error["reason"])

    @patch("model.users.UsersModel")
    def test_locked_incompatible_does_not_clear_preference(self, mock_users):
        mock_users.get_implementation_preference.return_value = "reject_video_9022"
        mock_users.is_implementation_locked.return_value = True
        self._register([
            ("reject_video_9022", RejectVideoDriver, 100),
            ("accept_video_9022", MockDriver, 200),
        ])
        tool = SimpleNamespace(video_path="/upload/ref.mp4")
        name, error = VideoDriverFactory.resolve_implementation_for_user(
            self.TASK_TYPE_ID, user_id=1, compatibility_tool=tool,
        )
        self.assertIsNone(name)
        self.assertEqual(error["reason"], DRIVER_ERROR_FIXED_IMPLEMENTATION_INPUT_INCOMPATIBLE)
        self.assertIn("不支持参考视频", error["message"])
        mock_users.clear_implementation_preference.assert_not_called()

    def test_parallel_locked_missing_impls_keep_own_messages(self):
        self._register([
            ("accept_video_9022", MockDriver, 100),
        ])

        def pref(user_id, task_key):
            return "gone-alpha" if int(user_id) == 11 else "gone-beta"

        barrier = threading.Barrier(2)
        results = {}

        def run(user_id):
            try:
                barrier.wait(timeout=5)
                name, error = VideoDriverFactory.resolve_implementation_for_user(
                    self.TASK_TYPE_ID, user_id=user_id,
                )
                results[user_id] = (name, error, None)
            except Exception as exc:  # noqa: BLE001
                results[user_id] = (None, None, exc)

        with patch("model.users.UsersModel.get_implementation_preference", side_effect=pref), \
                patch("model.users.UsersModel.is_implementation_locked", return_value=True), \
                patch("model.users.UsersModel.clear_implementation_preference", return_value=None):
            threads = [
                threading.Thread(target=run, args=(11,)),
                threading.Thread(target=run, args=(22,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertIsNone(results[11][2])
        self.assertIsNone(results[22][2])
        self.assertIsNone(results[11][0])
        self.assertIsNone(results[22][0])
        self.assertIn("gone-alpha", results[11][1]["message"])
        self.assertIn("gone-beta", results[22][1]["message"])
        self.assertNotIn("gone-beta", results[11][1]["message"])
        self.assertNotIn("gone-alpha", results[22][1]["message"])
