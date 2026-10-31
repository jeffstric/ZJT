"""失效实现方偏好批量清理服务测试（services/implementation_preference_cleanup）。

场景：管理端禁用实现方 / 清空其必需配置后，所有用户指向该实现方的
偏好与固定标记应被主动清除，避免固定任务持续失败且无法解除。
"""
import json
from unittest.mock import patch

from services.implementation_preference_cleanup import (
    cleanup_preferences_for_implementations,
    find_affected_implementations,
)


def _pref_payload(prefs, locks=None):
    group = {"name": "默认配置", "preferences": prefs}
    if locks is not None:
        group["locks"] = locks
    return {"groups": {"1": group}}


class TestFindAffectedImplementations:
    def test_matches_required_config_keys(self):
        impl = type("Impl", (), {"required_config_keys": ["topenrouter.api_key"]})()
        with patch(
            "services.implementation_preference_cleanup.UnifiedConfigRegistry.get_all_implementations",
            return_value={"seedance_2_0_mini_topenrouter_v1": impl},
        ):
            assert find_affected_implementations(["topenrouter.api_key"]) == [
                "seedance_2_0_mini_topenrouter_v1"
            ]

    def test_no_match_returns_empty(self):
        impl = type("Impl", (), {"required_config_keys": ["duomi.token"]})()
        with patch(
            "services.implementation_preference_cleanup.UnifiedConfigRegistry.get_all_implementations",
            return_value={"sora2_duomi_v1": impl},
        ):
            assert find_affected_implementations(["topenrouter.api_key"]) == []

    def test_empty_keys_returns_empty(self):
        assert find_affected_implementations([]) == []
        assert find_affected_implementations([None, ""]) == []


class TestCleanupPreferencesForImplementations:
    def _row(self, user_id, payload):
        return {"id": user_id, "implementation_preferences": json.dumps(payload, ensure_ascii=False)}

    @patch("services.implementation_preference_cleanup.execute_update")
    @patch("services.implementation_preference_cleanup.execute_query")
    def test_clears_stale_preference_and_lock(self, mock_q, mock_u):
        mock_q.return_value = [
            self._row(1, _pref_payload(
                {"t1": "impl_a", "t2": "impl_b"},
                {"t1": True, "t2": True},
            ))
        ]
        mock_u.return_value = 1

        result = cleanup_preferences_for_implementations(["impl_a"])

        assert result == {"scanned": 1, "cleared_users": 1}
        assert mock_u.call_count == 1
        saved = json.loads(mock_u.call_args[0][1][0])
        group = saved["groups"]["1"]
        assert group["preferences"] == {"t2": "impl_b"}
        assert group["locks"] == {"t2": True}

    @patch("services.implementation_preference_cleanup.execute_update")
    @patch("services.implementation_preference_cleanup.execute_query")
    def test_untouched_user_not_written_back(self, mock_q, mock_u):
        """预筛命中但偏好值不属于目标实现方：不写回。"""
        mock_q.return_value = [
            self._row(1, _pref_payload({"t1": "impl_other"}, {"t1": True}))
        ]

        result = cleanup_preferences_for_implementations(["impl_a"])

        assert result == {"scanned": 1, "cleared_users": 0}
        assert mock_u.call_count == 0

    @patch("services.implementation_preference_cleanup.execute_update")
    @patch("services.implementation_preference_cleanup.execute_query")
    def test_legacy_payload_without_locks(self, mock_q, mock_u):
        mock_q.return_value = [self._row(1, _pref_payload({"t1": "impl_a"}))]
        mock_u.return_value = 1

        result = cleanup_preferences_for_implementations(["impl_a"])

        assert result == {"scanned": 1, "cleared_users": 1}
        saved = json.loads(mock_u.call_args[0][1][0])
        assert saved["groups"]["1"]["preferences"] == {}

    @patch("services.implementation_preference_cleanup.execute_update")
    @patch("services.implementation_preference_cleanup.execute_query")
    def test_invalid_json_row_skipped(self, mock_q, mock_u):
        mock_q.return_value = [{"id": 1, "implementation_preferences": "not-json"}]

        result = cleanup_preferences_for_implementations(["impl_a"])

        assert result == {"scanned": 1, "cleared_users": 0}
        assert mock_u.call_count == 0

    def test_empty_names_no_query(self):
        with patch("services.implementation_preference_cleanup.execute_query") as mock_q:
            result = cleanup_preferences_for_implementations([])
        assert result == {"scanned": 0, "cleared_users": 0}
        assert mock_q.call_count == 0
