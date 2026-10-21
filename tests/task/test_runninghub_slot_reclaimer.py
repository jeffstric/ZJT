"""RunningHub 槽位对账回收守护单元测试。

核心设计约束：回收判定只依赖「任务是否活跃」（ai_tools.status），
不感知任何具体业务动作（提交/取消/重试）——终态 = 活跃集合之外的
一切状态值，未来新增终态自动被兜底覆盖。
"""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from task import runninghub_slot_reclaimer as rc


def _row(task_id=1, ai_id=1, ai_status=2, completed_minutes_ago=30):
    return {
        "task_id": task_id,
        "slot_id": task_id,
        "ai_id": ai_id,
        "ai_status": ai_status,
        "completed_time": datetime.now() - timedelta(minutes=completed_minutes_ago),
    }


class TestReclaimStaleSlots(unittest.TestCase):
    def run_reclaim(self, rows, grace_seconds=600):
        with patch.object(rc, "execute_query", return_value=rows), \
             patch.object(rc, "get_reclaim_grace_seconds", return_value=grace_seconds), \
             patch.object(rc.RunningHubSlotsModel, "release_slot",
                          return_value=1) as mock_release:
            reclaimed = rc.reclaim_stale_slots()
        return reclaimed, mock_release

    def test_terminal_task_old_slot_reclaimed(self):
        """终态任务（超宽限）残留槽 → 回收"""
        reclaimed, mock_release = self.run_reclaim([_row(task_id=11, ai_status=2)])
        self.assertEqual(reclaimed, 1)
        mock_release.assert_called_once_with(11, source="task")

    def test_failed_task_old_slot_reclaimed(self):
        reclaimed, _ = self.run_reclaim([_row(task_id=12, ai_status=-1)])
        self.assertEqual(reclaimed, 1)

    def test_active_statuses_never_reclaimed(self):
        """全部活跃状态（调度器正在处理）绝不回收"""
        rows = [_row(task_id=20 + i, ai_status=s)
                for i, s in enumerate(rc.ACTIVE_AI_TOOL_STATUSES)]
        reclaimed, mock_release = self.run_reclaim(rows)
        self.assertEqual(reclaimed, 0)
        mock_release.assert_not_called()

    def test_terminal_within_grace_skipped(self):
        """终态刚落库（宽限期内，调度器可能在途提交）→ 跳过"""
        reclaimed, mock_release = self.run_reclaim(
            [_row(task_id=31, completed_minutes_ago=5)], grace_seconds=600
        )
        self.assertEqual(reclaimed, 0)
        mock_release.assert_not_called()

    def test_terminal_null_completed_time_skipped(self):
        """终态但 completed_time 为 NULL 的脏数据 → 保守跳过"""
        row = _row(task_id=41)
        row["completed_time"] = None
        reclaimed, mock_release = self.run_reclaim([row])
        self.assertEqual(reclaimed, 0)
        mock_release.assert_not_called()

    def test_missing_ai_tool_row_reclaimed(self):
        """ai_tools 记录已不存在（极端不一致）→ 回收"""
        reclaimed, mock_release = self.run_reclaim(
            [{"task_id": 51, "slot_id": 51, "ai_id": None,
              "ai_status": None, "completed_time": None}]
        )
        self.assertEqual(reclaimed, 1)
        mock_release.assert_called_once_with(51, source="task")

    def test_future_terminal_status_auto_covered(self):
        """未来新增的任意终态值（如 -2）自动被兜底覆盖——判定只看「非活跃」"""
        reclaimed, _ = self.run_reclaim([_row(task_id=61, ai_status=-2)])
        self.assertEqual(reclaimed, 1)

    def test_empty_slots_returns_zero(self):
        reclaimed, mock_release = self.run_reclaim([])
        self.assertEqual(reclaimed, 0)
        mock_release.assert_not_called()

    def test_scan_failure_returns_zero_not_raise(self):
        """扫描异常 → 记日志返回 0，绝不抛出（守护不能影响调度器）"""
        with patch.object(rc, "execute_query", side_effect=RuntimeError("db down")), \
             patch.object(rc.RunningHubSlotsModel, "release_slot") as mock_release:
            self.assertEqual(rc.reclaim_stale_slots(), 0)
        mock_release.assert_not_called()

    def test_no_dependency_on_cancel_symbols(self):
        """本模块不得引用任何取消相关常量（独立于取消功能的硬约束）"""
        import inspect
        source = inspect.getsource(rc)
        for banned in ("CANCEL", "cancel"):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
