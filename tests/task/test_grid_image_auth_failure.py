"""
grid_image_task 轮询认证失败（401/403）终止逻辑的单元测试。

背景（生产事故 app.2026-09-29）：任务 1337_0_50937 的 auth_token 快照失效后，
轮询 get-status 连续 401 共 105 次（每 10s 一条 WARNING）直到被其他链路终结。
修复后：连续认证失败达到 GridConfig.AUTH_FAILURE_TERMINATION_LIMIT 即标记任务
FAILED 终态并联动下游（状态文件 + 分镜批次 item）。

验证点：
1. _is_auth_failure 只认 HTTP 401/403，网络错误/其他 HTTP 错误不算；
2. 连续达阈值调用 _terminate_task_for_auth_failure：状态置 FAILED + 联动 + 计数清理；
3. 未达阈值仅告警，计数累加；
4. 轮询成功 / 非认证异常时计数清零。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from tests.base.test_isolation import stub_modules

with stub_modules({"model.database": MagicMock()}):
    import task.grid_image_task as grid_mod  # noqa: E402
    from task.grid_image_task import _is_auth_failure  # noqa: E402

from config.constant import GridConfig  # noqa: E402


def _http_error(status_code):
    response = MagicMock()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code} Error", response=response)


def _make_task(task_key="1337_0_50937", item_type=0):
    return SimpleNamespace(
        id=50937,
        task_key=task_key,
        item_type=item_type,
        item_name="50937",
        user_id=1337,
        world_id=1,
        project_id="50937",
    )


class TestIsAuthFailure(unittest.TestCase):
    """_is_auth_failure 只识别 HTTP 401/403"""

    def test_401_and_403_are_auth_failures(self):
        self.assertTrue(_is_auth_failure(_http_error(401)))
        self.assertTrue(_is_auth_failure(_http_error(403)))

    def test_other_http_errors_not_auth(self):
        self.assertFalse(_is_auth_failure(_http_error(404)))
        self.assertFalse(_is_auth_failure(_http_error(500)))

    def test_network_errors_not_auth(self):
        self.assertFalse(_is_auth_failure(requests.ConnectionError("refused")))
        self.assertFalse(_is_auth_failure(requests.Timeout("timed out")))
        # 无 response 的 HTTPError（手工构造）也不算
        self.assertFalse(_is_auth_failure(requests.HTTPError("401")))


class TestAuthFailureStreakTermination(unittest.TestCase):
    """连续认证失败的计数与终止"""

    def setUp(self):
        grid_mod._auth_failure_streaks.clear()

    def tearDown(self):
        grid_mod._auth_failure_streaks.clear()

    @patch("task.grid_image_task._mark_storyboard_grid_batch_items_failed")
    @patch("task.grid_image_task._update_task_status_file")
    @patch("task.grid_image_task.GridImageTasksModel")
    def test_terminate_marks_failed_and_cleans_streak(
            self, MockGridModel, mock_status_file, mock_batch_failed):
        task = _make_task()
        grid_mod._auth_failure_streaks[task.task_key] = GridConfig.AUTH_FAILURE_TERMINATION_LIMIT - 1

        grid_mod._terminate_task_for_auth_failure(task)

        # 状态置 FAILED，错误信息说明认证失败
        kwargs = MockGridModel.update_status.call_args.kwargs
        self.assertEqual(kwargs["status"], grid_mod.GridImageTaskStatus.FAILED)
        self.assertIn("认证失败", kwargs["error_message"])
        mock_status_file.assert_called_once()
        mock_batch_failed.assert_called_once()
        # 计数已清理
        self.assertNotIn(task.task_key, grid_mod._auth_failure_streaks)


class TestPollLoopAuthBranch(unittest.TestCase):
    """process_grid_image_tasks 的 except 分支：认证失败达阈值即终止"""

    def setUp(self):
        grid_mod._auth_failure_streaks.clear()

    def tearDown(self):
        grid_mod._auth_failure_streaks.clear()

    def _poll_once(self, task):
        """模拟调度器对一个任务执行一轮轮询（复用生产代码路径）。

        Returns:
            (轮询请求 mock, 本轮 update_status 调用记录)
        """
        status_calls = []
        with patch.object(grid_mod.GridImageTasksModel, "get_pending_tasks", return_value=[task]), \
                patch.object(grid_mod.GridImageTasksModel, "increment_try_count"), \
                patch.object(grid_mod.GridImageTasksModel, "update_status",
                             side_effect=lambda **kw: status_calls.append(kw)), \
                patch.object(grid_mod, "_update_task_status_file"), \
                patch.object(grid_mod, "_mark_storyboard_grid_batch_items_failed"), \
                patch.object(grid_mod, "_cleanup_orphan_grid_split_steps"), \
                patch.object(grid_mod.requests, "get",
                             side_effect=_http_error(401)) as mock_get:
            grid_mod.process_grid_image_tasks(app=None)
        return mock_get, status_calls

    @staticmethod
    def _make_pending_task():
        return SimpleNamespace(
            id=50937,
            task_key="1337_0_50937",
            item_type=0,
            item_name="50937",
            user_id=1337,
            world_id=1,
            project_id="50937",
            try_count=1,
            max_attempts=120,
            comfyui_base_url="http://ailive.perseids.cn",
            auth_token="deadbeef",
        )

    def test_terminates_after_consecutive_limit(self):
        """连续 LIMIT 次 401 后任务被标记终态 FAILED，不再继续轮询"""
        task = self._make_pending_task()
        all_status_calls = []
        for _ in range(GridConfig.AUTH_FAILURE_TERMINATION_LIMIT):
            _, status_calls = self._poll_once(task)
            all_status_calls.extend(status_calls)

        # 终止时计数被清理
        self.assertNotIn(task.task_key, grid_mod._auth_failure_streaks)
        # 最后一轮已写入终态 FAILED
        self.assertIn(grid_mod.GridImageTaskStatus.FAILED,
                      [c.get("status") for c in all_status_calls])

    def test_single_401_keeps_task_alive(self):
        """单次 401 不终止任务（只累加计数）"""
        task = self._make_pending_task()
        self._poll_once(task)
        self.assertEqual(
            grid_mod._auth_failure_streaks.get(task.task_key), 1,
        )

    def test_non_auth_error_resets_streak(self):
        """网络错误重置认证失败计数（streak 语义为连续）"""
        task = self._make_pending_task()
        grid_mod._auth_failure_streaks[task.task_key] = 2  # 已连续 2 次

        with patch.object(grid_mod.GridImageTasksModel, "get_pending_tasks", return_value=[task]), \
                patch.object(grid_mod.GridImageTasksModel, "increment_try_count"), \
                patch.object(grid_mod.GridImageTasksModel, "update_status"), \
                patch.object(grid_mod, "_update_task_status_file"), \
                patch.object(grid_mod, "_mark_storyboard_grid_batch_items_failed"), \
                patch.object(grid_mod, "_cleanup_orphan_grid_split_steps"), \
                patch.object(grid_mod.requests, "get",
                             side_effect=requests.ConnectionError("refused")):
            grid_mod.process_grid_image_tasks(app=None)

        self.assertNotIn(task.task_key, grid_mod._auth_failure_streaks)


if __name__ == "__main__":
    unittest.main()
