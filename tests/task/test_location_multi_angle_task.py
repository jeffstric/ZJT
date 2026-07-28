"""
location_multi_angle_task 模块的单元测试。

覆盖场景多角度生图任务的失败重试与终态判定回归点：
1. 提交失败重试状态机：第 1/2 次失败仅递增 current_angle_retry_count，
   达到 LOCATION_MULTI_ANGLE_SUBMIT_MAX_RETRY 次后跳过当前角度（index+1、retry 清零）；
2. 提交响应异常分支：project_ids=[]、status != submitted、error/detail 错误信息提取；
3. 全部角度处理完毕的终态判定（_finalize_task）：零产出必须 FAILED，
   部分产出 COMPLETED 并保留部分失败说明，避免前端"任务完成但无图片"。
"""
import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# 只 mock database 层，保持 model 包真实导入（与 test_grid_image_task_batch_failure.py 一致）
_saved_database = sys.modules.get("model.database")
sys.modules["model.database"] = MagicMock()

for _mod in [
    "model.location_multi_angle_tasks",
    "model.ai_tools",
    "task.location_multi_angle_task",
]:
    if _mod in sys.modules:
        importlib.reload(sys.modules[_mod])

from config.constant import (  # noqa: E402
    AI_TOOL_STATUS_COMPLETED,
    AI_TOOL_STATUS_FAILED,
    LOCATION_MULTI_ANGLE_SUBMIT_MAX_RETRY,
)
from model.location_multi_angle_tasks import LocationMultiAngleTaskStatus  # noqa: E402
from task import location_multi_angle_task as lmat  # noqa: E402

if _saved_database is not None:
    sys.modules["model.database"] = _saved_database
else:
    sys.modules.pop("model.database", None)


_ONE_ANGLE = [{"angle": 0, "angleKey": "front", "label": "正面"}]
_TWO_ANGLES = [
    {"angle": 0, "angleKey": "front", "label": "正面"},
    {"angle": 90, "angleKey": "right", "label": "右侧"},
]


def _make_task(angles=None, current_index=0, retry_count=0, generated=None,
               status=LocationMultiAngleTaskStatus.PROCESSING, ai_tool_task_id=None):
    """构造一个 location multi-angle task mock。"""
    angles = _TWO_ANGLES if angles is None else angles
    generated = generated or []
    return SimpleNamespace(
        task_key="test_ma_task",
        location_name="测试场景",
        user_id="u1",
        world_id="w1",
        main_image="http://example.com/main.png",
        model="",
        auth_token="",
        status=status,
        current_angle_index=current_index,
        current_angle_retry_count=retry_count,
        ai_tool_task_id=ai_tool_task_id,
        get_angles_list=lambda: list(angles),
        get_generated_images_list=lambda: list(generated),
    )


def _run_process(task, post_json=None, ai_tool=None):
    """运行 process_location_multi_angle_task，外部依赖全部打桩。

    Returns:
        (result, update_status_mock) 元组
    """
    with patch.object(lmat.LocationMultiAngleTasksModel, "get_by_task_key", return_value=task), \
         patch.object(lmat.LocationMultiAngleTasksModel, "update_status") as mock_update, \
         patch.object(lmat, "get_config", return_value={"server": {"host": "http://localhost:8188"}}), \
         patch("task.mock_interceptor.is_mock_enabled", return_value=False), \
         patch("config.unified_config.UnifiedConfigRegistry") as mock_registry, \
         patch.object(lmat.AIToolsModel, "get_by_id", return_value=ai_tool), \
         patch.object(lmat, "_download_and_store_image",
                      return_value=("http://localhost/img.png", "/tmp/img.png")), \
         patch.object(lmat, "_update_reference_images_to_staging", return_value=True), \
         patch.object(lmat, "requests") as mock_requests:
        mock_registry.get_by_key.return_value = SimpleNamespace(id=123)
        mock_response = MagicMock()
        mock_response.json.return_value = post_json or {}
        mock_requests.post.return_value = mock_response
        result = lmat.process_location_multi_angle_task(task.task_key)
    return result, mock_update


class TestHandleSubmitFailure(unittest.TestCase):
    """提交失败重试状态机：未达上限累加重试计数，达上限跳过当前角度。"""

    @patch.object(lmat.LocationMultiAngleTasksModel, "update_status")
    def test_first_failure_increments_retry(self, mock_update):
        """第 1 次失败：PROCESSING，index 不变，retry=1。"""
        task = _make_task(retry_count=0)
        lmat._handle_submit_failure(task, "k", "正面", 0, "boom")

        args, kwargs = mock_update.call_args
        self.assertEqual(args[1], LocationMultiAngleTaskStatus.PROCESSING)
        self.assertEqual(kwargs["current_angle_retry_count"], 1)
        self.assertNotIn("current_angle_index", kwargs)
        self.assertIn("boom", kwargs["error_message"])

    @patch.object(lmat.LocationMultiAngleTasksModel, "update_status")
    def test_second_failure_increments_retry(self, mock_update):
        """第 2 次失败：PROCESSING，index 不变，retry=2。"""
        task = _make_task(retry_count=1)
        lmat._handle_submit_failure(task, "k", "正面", 0, "boom")

        _, kwargs = mock_update.call_args
        self.assertEqual(kwargs["current_angle_retry_count"], 2)
        self.assertNotIn("current_angle_index", kwargs)

    @patch.object(lmat.LocationMultiAngleTasksModel, "update_status")
    def test_max_retry_skips_angle(self, mock_update):
        """达到重试上限：跳过当前角度（index+1），retry 清零。"""
        task = _make_task(retry_count=LOCATION_MULTI_ANGLE_SUBMIT_MAX_RETRY - 1)
        lmat._handle_submit_failure(task, "k", "正面", 0, "boom")

        args, kwargs = mock_update.call_args
        self.assertEqual(args[1], LocationMultiAngleTaskStatus.PROCESSING)
        self.assertEqual(kwargs["current_angle_index"], 1)
        self.assertEqual(kwargs["current_angle_retry_count"], 0)
        self.assertEqual(kwargs["ai_tool_task_id"], 0)


class TestSubmitFailureResponses(unittest.TestCase):
    """/api/image-edit 异常响应分支：project_ids=[]、status != submitted、error/detail。"""

    def test_empty_project_ids_retries(self):
        """status=submitted 但 project_ids=[] 视为提交失败，计入重试。"""
        task = _make_task(retry_count=0)
        result, mock_update = _run_process(task, {"status": "submitted", "project_ids": []})

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "未返回 project_id")
        _, kwargs = mock_update.call_args
        self.assertEqual(kwargs["current_angle_retry_count"], 1)

    def test_non_submitted_status_uses_error_field(self):
        """status != submitted 时取 error 字段作为错误信息。"""
        task = _make_task(retry_count=0)
        result, mock_update = _run_process(task, {"status": "failed", "error": "队列已满"})

        self.assertFalse(result["success"])
        _, kwargs = mock_update.call_args
        self.assertEqual(kwargs["current_angle_retry_count"], 1)
        self.assertIn("队列已满", kwargs["error_message"])

    def test_non_submitted_status_uses_detail_field(self):
        """无 error 字段时回退取 detail 字段作为错误信息。"""
        task = _make_task(retry_count=0)
        result, mock_update = _run_process(task, {"status": "failed", "detail": "算力不足"})

        self.assertFalse(result["success"])
        _, kwargs = mock_update.call_args
        self.assertIn("算力不足", kwargs["error_message"])

    def test_third_failure_skips_angle(self):
        """第 3 次提交失败：跳过当前角度（index+1），retry 清零。"""
        task = _make_task(retry_count=LOCATION_MULTI_ANGLE_SUBMIT_MAX_RETRY - 1, current_index=0)
        result, mock_update = _run_process(task, {"status": "failed", "error": "boom"})

        self.assertFalse(result["success"])
        args, kwargs = mock_update.call_args
        self.assertEqual(args[1], LocationMultiAngleTaskStatus.PROCESSING)
        self.assertEqual(kwargs["current_angle_index"], 1)
        self.assertEqual(kwargs["current_angle_retry_count"], 0)


class TestFinalizeTask(unittest.TestCase):
    """全部角度处理完毕的终态判定：零产出 FAILED，部分产出 COMPLETED 附说明。"""

    def test_zero_output_marks_failed(self):
        """全部角度失败（零产出）：终态 FAILED，而非 COMPLETED。"""
        task = _make_task(angles=_ONE_ANGLE, current_index=1, generated=[])
        result, mock_update = _run_process(task)

        self.assertFalse(result["success"])
        args, kwargs = mock_update.call_args
        self.assertEqual(args[1], LocationMultiAngleTaskStatus.FAILED)
        self.assertIn("0/1", kwargs["error_message"])

    def test_partial_output_marks_completed_with_note(self):
        """部分角度成功：终态 COMPLETED，error_message 保留部分失败说明。"""
        task = _make_task(current_index=2, generated=[{"angle": "front", "url": "u"}])
        result, mock_update = _run_process(task)

        self.assertTrue(result["success"])
        args, kwargs = mock_update.call_args
        self.assertEqual(args[1], LocationMultiAngleTaskStatus.COMPLETED)
        self.assertIn("1/2", kwargs["error_message"])

    def test_full_output_marks_completed_without_note(self):
        """全部角度成功：终态 COMPLETED，无部分失败说明。"""
        task = _make_task(angles=_ONE_ANGLE, current_index=1,
                          generated=[{"angle": "front", "url": "u"}])
        result, mock_update = _run_process(task)

        self.assertTrue(result["success"])
        args, kwargs = mock_update.call_args
        self.assertEqual(args[1], LocationMultiAngleTaskStatus.COMPLETED)
        self.assertIsNone(kwargs["error_message"])

    def test_already_finished_task_not_updated_again(self):
        """已终态（FAILED/COMPLETED）的任务不重复回写状态。"""
        task = _make_task(angles=_ONE_ANGLE, current_index=1, generated=[],
                          status=LocationMultiAngleTaskStatus.FAILED)
        result, mock_update = _run_process(task)

        self.assertTrue(result["success"])
        mock_update.assert_not_called()


class TestAIToolTerminalStates(unittest.TestCase):
    """轮询中的 AI 任务进入终态后的处理。"""

    def test_ai_failed_zero_output_marks_failed(self):
        """最后一个角度的 AI 任务失败且零产出：终态 FAILED。"""
        task = _make_task(angles=_ONE_ANGLE, current_index=0, generated=[], ai_tool_task_id=555)
        ai_tool = SimpleNamespace(status=AI_TOOL_STATUS_FAILED, message="生成失败")
        result, mock_update = _run_process(task, ai_tool=ai_tool)

        self.assertFalse(result["success"])
        # 最后一次回写应把任务置 FAILED（前面还有一次 PROCESSING 推进 index）
        args, kwargs = mock_update.call_args
        self.assertEqual(args[1], LocationMultiAngleTaskStatus.FAILED)
        self.assertIn("0/1", kwargs["error_message"])

    def test_ai_completed_last_angle_marks_completed(self):
        """最后一个角度的 AI 任务完成：终态 COMPLETED，无失败说明。"""
        task = _make_task(angles=_ONE_ANGLE, current_index=0, generated=[], ai_tool_task_id=556)
        ai_tool = SimpleNamespace(status=AI_TOOL_STATUS_COMPLETED,
                                  result_url="http://example.com/r.png")
        result, mock_update = _run_process(task, ai_tool=ai_tool)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["generated_images"]), 1)
        args, kwargs = mock_update.call_args
        self.assertEqual(args[1], LocationMultiAngleTaskStatus.COMPLETED)
        self.assertIsNone(kwargs["error_message"])

    def test_ai_completed_partial_marks_completed_with_note(self):
        """部分角度失败被跳过、其余成功：终态 COMPLETED 且保留 M/N 说明。"""
        # 角度 0 此前已失败被跳过（generated 为空、index 已推进到 1），角度 1 成功
        task = _make_task(current_index=1, generated=[], ai_tool_task_id=557)
        ai_tool = SimpleNamespace(status=AI_TOOL_STATUS_COMPLETED,
                                  result_url="http://example.com/r.png")
        result, mock_update = _run_process(task, ai_tool=ai_tool)

        self.assertTrue(result["success"])
        args, kwargs = mock_update.call_args
        self.assertEqual(args[1], LocationMultiAngleTaskStatus.COMPLETED)
        self.assertIn("1/2", kwargs["error_message"])


if __name__ == "__main__":
    unittest.main()
