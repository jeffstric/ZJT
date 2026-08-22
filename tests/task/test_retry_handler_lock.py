"""固定供应商任务跳过 implementation_retry。"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config.constant import IMPLEMENTATION_LOCK_EXTRA_CONFIG_KEY

# enterprise/ 被 .gitignore，社区 CI 镜像不会 COPY 该包。
# 模块级 ImportError 会被 unittest 记为 ERROR 而非 skip，必须在导入处吞掉。
try:
    from enterprise.task.retry_handler import (
        handle_failure_with_retry,
        is_implementation_locked_task,
    )
except (ModuleNotFoundError, ImportError):
    handle_failure_with_retry = None
    is_implementation_locked_task = None

_HAS_ENTERPRISE_RETRY = handle_failure_with_retry is not None


@unittest.skipUnless(_HAS_ENTERPRISE_RETRY, "enterprise 模块未打包")
class TestIsImplementationLockedTask(unittest.TestCase):
    def test_snapshot_true(self):
        ai_tool = SimpleNamespace(extra_config=json.dumps({IMPLEMENTATION_LOCK_EXTRA_CONFIG_KEY: True}))
        self.assertTrue(is_implementation_locked_task(ai_tool, 1, 27))

    def test_snapshot_false_honored(self):
        ai_tool = SimpleNamespace(extra_config={IMPLEMENTATION_LOCK_EXTRA_CONFIG_KEY: False})
        self.assertFalse(is_implementation_locked_task(ai_tool, 1, 27))

    @patch("model.users.UsersModel")
    @patch("config.unified_config.UnifiedConfigRegistry")
    def test_missing_snapshot_falls_back_to_live_lock(self, mock_registry, mock_users):
        mock_registry.get_by_id.return_value = MagicMock(key="grok_image_to_video")
        mock_users.is_implementation_locked.return_value = True
        ai_tool = SimpleNamespace(extra_config=None)
        self.assertTrue(is_implementation_locked_task(ai_tool, 8, 27))
        mock_users.is_implementation_locked.assert_called_once_with(8, "grok_image_to_video")


@unittest.skipUnless(_HAS_ENTERPRISE_RETRY, "enterprise 模块未打包")
class TestHandleFailureWithRetryLock(unittest.TestCase):
    @patch("enterprise.task.retry_handler.PipelineDriverFactory")
    @patch("enterprise.task.retry_handler.AIToolsModel")
    @patch("config.config_util.get_dynamic_config_value")
    def test_locked_snapshot_skips_candidate_selection(
        self, mock_config, mock_ai_tools, mock_factory
    ):
        mock_config.return_value = True
        mock_ai_tools.get_by_id.return_value = SimpleNamespace(
            extra_config=json.dumps({IMPLEMENTATION_LOCK_EXTRA_CONFIG_KEY: True}),
            implementation=12,
        )
        result = handle_failure_with_retry(101, 27, "upstream failed", user_id=1)
        self.assertIsNone(result)
        mock_factory.select_before_finish_retry_candidate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
