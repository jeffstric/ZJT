"""users.implementation_preferences JSON 中 locks 字段的纯逻辑与模型读写测试。"""
import json
import unittest
from unittest.mock import patch

from model.users import (
    UsersModel,
    collect_true_locks,
    get_active_preference_group_data,
    get_group_lock_map,
    get_group_preference_map,
    is_task_implementation_locked,
    parse_implementation_preferences,
)


class TestPreferenceLockHelpers(unittest.TestCase):
    def test_parse_empty_and_invalid(self):
        self.assertEqual(parse_implementation_preferences(None), {})
        self.assertEqual(parse_implementation_preferences(""), {})
        self.assertEqual(parse_implementation_preferences("not-json"), {})
        self.assertEqual(parse_implementation_preferences([1, 2]), {})

    def test_legacy_json_without_locks_is_unlocked(self):
        raw = {
            "groups": {
                "1": {
                    "name": "默认配置",
                    "preferences": {"grok_image_to_video": "grok_duomi_v1"},
                }
            }
        }
        group = get_active_preference_group_data(raw, 1)
        self.assertEqual(get_group_preference_map(group)["grok_image_to_video"], "grok_duomi_v1")
        self.assertEqual(get_group_lock_map(group), {})
        self.assertFalse(is_task_implementation_locked(group, "grok_image_to_video"))
        self.assertEqual(collect_true_locks(group), {})

    def test_locked_true_requires_matching_preference(self):
        group = {
            "preferences": {"grok_image_to_video": "grok_duomi_v1"},
            "locks": {"grok_image_to_video": True, "orphan": True, "off": False},
        }
        self.assertTrue(is_task_implementation_locked(group, "grok_image_to_video"))
        self.assertFalse(is_task_implementation_locked(group, "orphan"))
        self.assertFalse(is_task_implementation_locked(group, "off"))
        self.assertEqual(collect_true_locks(group), {"grok_image_to_video": True})

    def test_locks_non_dict_treated_as_empty(self):
        group = {
            "preferences": {"k": "impl"},
            "locks": "bad",
        }
        self.assertEqual(get_group_lock_map(group), {})
        self.assertFalse(is_task_implementation_locked(group, "k"))


class TestUsersModelPreferenceLocks(unittest.TestCase):
    def _row(self, payload, group=1):
        return {
            "implementation_preferences": json.dumps(payload, ensure_ascii=False),
            "active_preference_group": group,
        }

    @patch("model.users.execute_query")
    def test_is_locked_false_for_legacy_row(self, mock_query):
        mock_query.return_value = self._row({
            "groups": {"1": {"preferences": {"k": "impl_a"}}}
        })
        self.assertFalse(UsersModel.is_implementation_locked(1, "k"))
        self.assertEqual(UsersModel.get_all_locks(1), {})

    @patch("model.users.execute_update")
    @patch("model.users.execute_query")
    def test_set_locked_true_writes_locks(self, mock_query, mock_update):
        mock_query.return_value = self._row({
            "groups": {"1": {"name": "默认配置", "preferences": {}}}
        })
        mock_update.return_value = 1
        UsersModel.set_implementation_preference(9, "k", "impl_a", locked=True)
        saved = json.loads(mock_update.call_args[0][1][0])
        self.assertEqual(saved["groups"]["1"]["preferences"]["k"], "impl_a")
        self.assertTrue(saved["groups"]["1"]["locks"]["k"])

    @patch("model.users.execute_update")
    @patch("model.users.execute_query")
    def test_set_locked_false_removes_lock(self, mock_query, mock_update):
        mock_query.return_value = self._row({
            "groups": {
                "1": {
                    "preferences": {"k": "impl_a"},
                    "locks": {"k": True},
                }
            }
        })
        mock_update.return_value = 1
        UsersModel.set_implementation_preference(9, "k", "impl_b", locked=False)
        saved = json.loads(mock_update.call_args[0][1][0])
        self.assertEqual(saved["groups"]["1"]["preferences"]["k"], "impl_b")
        self.assertNotIn("k", saved["groups"]["1"].get("locks") or {})

    @patch("model.users.execute_update")
    @patch("model.users.execute_query")
    def test_clear_removes_preference_and_lock(self, mock_query, mock_update):
        mock_query.return_value = self._row({
            "groups": {
                "1": {
                    "preferences": {"k": "impl_a", "other": "impl_b"},
                    "locks": {"k": True},
                }
            }
        })
        mock_update.return_value = 1
        UsersModel.clear_implementation_preference(9, "k")
        saved = json.loads(mock_update.call_args[0][1][0])
        self.assertNotIn("k", saved["groups"]["1"]["preferences"])
        self.assertNotIn("k", saved["groups"]["1"].get("locks") or {})
        self.assertEqual(saved["groups"]["1"]["preferences"]["other"], "impl_b")


if __name__ == "__main__":
    unittest.main()
