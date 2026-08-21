"""ai_tools extra_config 固定供应商快照 merge 测试。"""
import json
import unittest
from unittest.mock import MagicMock, patch

from config.constant import IMPLEMENTATION_LOCK_EXTRA_CONFIG_KEY
from model.ai_tools import (
    apply_implementation_lock_snapshot,
    merge_implementation_lock_into_extra_config,
    parse_extra_config_dict,
)


class TestApplyImplementationLockSnapshot(unittest.TestCase):
    def test_writes_true_into_empty_config(self):
        result = apply_implementation_lock_snapshot(None, locked=True)
        self.assertEqual(json.loads(result), {IMPLEMENTATION_LOCK_EXTRA_CONFIG_KEY: True})

    def test_false_leaves_original(self):
        self.assertIsNone(apply_implementation_lock_snapshot(None, locked=False))
        original = json.dumps({"image_mode": "first_last_frame"})
        self.assertEqual(apply_implementation_lock_snapshot(original, locked=False), original)

    def test_does_not_override_existing_key(self):
        original = json.dumps({IMPLEMENTATION_LOCK_EXTRA_CONFIG_KEY: False, "keep": 1})
        result = apply_implementation_lock_snapshot(original, locked=True)
        self.assertEqual(result, original)

    def test_merges_into_existing_object(self):
        original = json.dumps({"image_mode": "first_last_frame"})
        result = apply_implementation_lock_snapshot(original, locked=True)
        parsed = json.loads(result)
        self.assertTrue(parsed[IMPLEMENTATION_LOCK_EXTRA_CONFIG_KEY])
        self.assertEqual(parsed["image_mode"], "first_last_frame")

    def test_parse_invalid(self):
        self.assertEqual(parse_extra_config_dict("not-json"), {})
        self.assertEqual(parse_extra_config_dict([1]), {})


class TestMergeImplementationLockIntoExtraConfig(unittest.TestCase):
    @patch("model.users.UsersModel")
    @patch("config.unified_config.UnifiedConfigRegistry")
    @patch("config.unified_config.get_implementation_name")
    def test_writes_when_locked_impl_matches(self, mock_name, mock_registry, mock_users):
        mock_registry.get_by_id.return_value = MagicMock(key="grok_image_to_video")
        mock_users.is_implementation_locked.return_value = True
        mock_users.get_implementation_preference.return_value = "grok_duomi_v1"
        mock_name.return_value = "grok_duomi_v1"

        result = merge_implementation_lock_into_extra_config("{}", 1, 27, 12)
        self.assertTrue(json.loads(result)[IMPLEMENTATION_LOCK_EXTRA_CONFIG_KEY])

    @patch("model.users.UsersModel")
    @patch("config.unified_config.UnifiedConfigRegistry")
    @patch("config.unified_config.get_implementation_name")
    def test_skips_when_impl_does_not_match(self, mock_name, mock_registry, mock_users):
        mock_registry.get_by_id.return_value = MagicMock(key="grok_image_to_video")
        mock_users.is_implementation_locked.return_value = True
        mock_users.get_implementation_preference.return_value = "grok_duomi_v1"
        mock_name.return_value = "grok_other_v1"

        original = json.dumps({"keep": True})
        result = merge_implementation_lock_into_extra_config(original, 1, 27, 99)
        self.assertEqual(result, original)


if __name__ == "__main__":
    unittest.main()
