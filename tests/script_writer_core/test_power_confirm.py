"""算力确认门纯逻辑测试。"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

import importlib.util

_POWER_CONFIRM_PATH = os.path.join(
    project_root, "script_writer_core", "agents", "power_confirm.py"
)
_spec = importlib.util.spec_from_file_location("power_confirm_under_test", _POWER_CONFIRM_PATH)
power_confirm = importlib.util.module_from_spec(_spec)
sys.modules["power_confirm_under_test"] = power_confirm
_spec.loader.exec_module(power_confirm)

ConfirmAnswer = power_confirm.ConfirmAnswer
OPTION_APPROVE = power_confirm.OPTION_APPROVE
OPTION_REJECT = power_confirm.OPTION_REJECT
OPTION_SKIP_SESSION = power_confirm.OPTION_SKIP_SESSION
get_effective_thresholds = power_confirm.get_effective_thresholds
parse_confirm_answer = power_confirm.parse_confirm_answer
should_confirm = power_confirm.should_confirm
validate_threshold = power_confirm.validate_threshold


class TestShouldConfirm(unittest.TestCase):
    def test_low_cost_skips(self):
        decision = should_confirm(2, 0, False, 35, 200)
        self.assertFalse(decision.need_confirm)
        self.assertEqual(decision.reason, "below_threshold")

    def test_exactly_threshold_skips(self):
        decision = should_confirm(35, 0, False, 35, 200)
        self.assertFalse(decision.need_confirm)

    def test_over_soft_confirms(self):
        decision = should_confirm(36, 0, False, 35, 200)
        self.assertTrue(decision.need_confirm)
        self.assertEqual(decision.reason, "over_soft")

    def test_accumulate_over_soft(self):
        decision = should_confirm(10, 30, False, 35, 200)
        self.assertTrue(decision.need_confirm)
        self.assertEqual(decision.projected_total, 40)

    def test_skip_allows_below_hard(self):
        decision = should_confirm(80, 0, True, 35, 200)
        self.assertFalse(decision.need_confirm)

    def test_skip_still_blocks_over_hard(self):
        decision = should_confirm(201, 0, True, 35, 200)
        self.assertTrue(decision.need_confirm)
        self.assertEqual(decision.reason, "over_hard")

    def test_unknown_always_confirms(self):
        decision = should_confirm(0, 0, False, 35, 200, unknown=True)
        self.assertTrue(decision.need_confirm)
        self.assertEqual(decision.reason, "unknown")

    def test_user_a_vs_user_b_thresholds(self):
        # 同样 20 算力：阈值 10 要问，阈值 80 不问
        self.assertTrue(should_confirm(20, 0, False, 10, 200).need_confirm)
        self.assertFalse(should_confirm(20, 0, False, 80, 200).need_confirm)

    def test_zero_threshold_always_asks(self):
        self.assertTrue(should_confirm(2, 0, False, 0, 200).need_confirm)


class TestParseConfirmAnswer(unittest.TestCase):
    def test_exact_options(self):
        self.assertEqual(parse_confirm_answer(OPTION_APPROVE), ConfirmAnswer.APPROVE)
        self.assertEqual(parse_confirm_answer(OPTION_REJECT), ConfirmAnswer.REJECT)
        self.assertEqual(parse_confirm_answer(OPTION_SKIP_SESSION), ConfirmAnswer.SKIP_SESSION)

    def test_synonyms(self):
        self.assertEqual(parse_confirm_answer("确认"), ConfirmAnswer.APPROVE)
        self.assertEqual(parse_confirm_answer("取消吧"), ConfirmAnswer.REJECT)
        self.assertEqual(parse_confirm_answer("不用问我了"), ConfirmAnswer.SKIP_SESSION)
        self.assertEqual(parse_confirm_answer("直接生成"), ConfirmAnswer.SKIP_SESSION)

    def test_empty_or_unknown_is_reject(self):
        self.assertEqual(parse_confirm_answer(""), ConfirmAnswer.REJECT)
        self.assertEqual(parse_confirm_answer("随便看看"), ConfirmAnswer.REJECT)


class TestValidateThreshold(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_threshold(0), 0)
        self.assertEqual(validate_threshold("35"), 35)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            validate_threshold(-1)
        with self.assertRaises(ValueError):
            validate_threshold("abc")
        with self.assertRaises(ValueError):
            validate_threshold(1.5)
        with self.assertRaises(ValueError):
            validate_threshold(None)


class TestResolveUserThreshold(unittest.TestCase):
    def _fake_pref_module(self, pref=None, error=None):
        fake = MagicMock()
        fake.PREF_TYPE_POWER_CONFIRM = "power_confirm"
        if error:
            fake.UserPreferencesModel.get.side_effect = error
        else:
            fake.UserPreferencesModel.get.return_value = pref
        return fake

    @patch.object(power_confirm, "get_platform_thresholds", return_value=(35, 200))
    def test_unset_falls_back_to_platform(self, _mock_platform):
        fake = self._fake_pref_module(pref=None)
        with patch.dict(sys.modules, {"model.user_preferences": fake}):
            soft, hard, is_custom = get_effective_thresholds("1")
        self.assertEqual(soft, 35)
        self.assertEqual(hard, 200)
        self.assertFalse(is_custom)

    @patch.object(power_confirm, "get_platform_thresholds", return_value=(35, 200))
    def test_user_custom_threshold(self, _mock_platform):
        pref = MagicMock()
        pref.config_value = {"threshold": 10}
        pref.get_value.return_value = {"threshold": 10}
        fake = self._fake_pref_module(pref=pref)
        with patch.dict(sys.modules, {"model.user_preferences": fake}):
            soft, hard, is_custom = get_effective_thresholds("2")
        self.assertEqual(soft, 10)
        self.assertEqual(hard, 200)
        self.assertTrue(is_custom)

    @patch.object(power_confirm, "get_platform_thresholds", return_value=(35, 200))
    def test_db_error_falls_back(self, _mock_platform):
        fake = self._fake_pref_module(error=RuntimeError("db"))
        with patch.dict(sys.modules, {"model.user_preferences": fake}):
            soft, hard, is_custom = get_effective_thresholds("3")
        self.assertEqual(soft, 35)
        self.assertFalse(is_custom)


class TestGateDecisionWiring(unittest.TestCase):
    """不依赖 ExpertAgent 导入，验证门控决策与回答解析的组合。"""

    def test_reject_means_do_not_execute(self):
        decision = should_confirm(80, 0, False, 35, 200)
        self.assertTrue(decision.need_confirm)
        self.assertEqual(parse_confirm_answer(OPTION_REJECT), ConfirmAnswer.REJECT)

    def test_approve_after_confirm(self):
        decision = should_confirm(80, 0, False, 35, 200)
        self.assertTrue(decision.need_confirm)
        self.assertEqual(parse_confirm_answer(OPTION_APPROVE), ConfirmAnswer.APPROVE)

    def test_skip_session_then_below_hard(self):
        self.assertEqual(parse_confirm_answer(OPTION_SKIP_SESSION), ConfirmAnswer.SKIP_SESSION)
        self.assertFalse(should_confirm(80, 0, True, 35, 200).need_confirm)
        self.assertTrue(should_confirm(250, 0, True, 35, 200).need_confirm)


if __name__ == "__main__":
    unittest.main()
