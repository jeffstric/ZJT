"""
grid_image_task 模块的单元测试。

重点验证：当分镜首帧宫格任务（item_type=STORYBOARD_FIRST_FRAME_GRID）进入终态失败
（超时 / FAILED / 异常 / 下载失败）时，_mark_storyboard_grid_batch_items_failed 能正确把关联的
storyboard_image_batch_item 从 RUNNING 回写为 FAILED，并把绑定的 ai_tool_pipeline_steps
grid split step 从 PENDING 回写为 FAILED，避免 step 永久卡死被全局调度器反复 skip 刷日志。
"""
import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# 只 mock database 层，保持 model 包真实导入（与 test_pipeline_processor.py 一致）
_saved_database = sys.modules.get("model.database")
sys.modules["model.database"] = MagicMock()

for _mod in [
    "model.grid_image_tasks",
    "model.ai_tools",
    "model.storyboard_image_batch",
    "task.grid_image_task",
]:
    if _mod in sys.modules:
        importlib.reload(sys.modules[_mod])

from config.constant import StoryboardAutoGenerateConstants  # noqa: E402
from task.grid_image_task import (  # noqa: E402
    _mark_storyboard_grid_batch_items_failed,
    _fail_pending_grid_split_step_for_task,
    _cleanup_orphan_grid_split_steps,
)

if _saved_database is not None:
    sys.modules["model.database"] = _saved_database
else:
    sys.modules.pop("model.database", None)


def _make_task(scene_ids, grid_task_id=454, item_type=8, project_id="1075"):
    """构造一个 grid task mock。item_type=8 即 STORYBOARD_FIRST_FRAME_GRID。"""
    return SimpleNamespace(
        id=grid_task_id,
        task_key="grid:1:2:1075",
        item_type=item_type,
        project_id=project_id,
        get_target_entity_ids_list=lambda: list(scene_ids),
    )


class TestMarkStoryboardGridBatchItemsFailed(unittest.TestCase):
    """_mark_storyboard_grid_batch_items_failed 应把所有 RUNNING item 回写 FAILED。"""

    @patch("model.storyboard_image_batch.StoryboardImageBatchItemModel")
    def test_marks_all_running_items_failed(self, MockBatchModel):
        """对每个 scene 的 RUNNING batch item，回写 status=FAILED + error_code。"""
        scene_ids = [415, 416, 417, 418]
        task = _make_task(scene_ids)

        def fake_find(grid_task_id, scene_id):
            return {"id": 1000 + scene_id, "extra_json": {"grid_task_id": grid_task_id}}

        MockBatchModel.find_running_by_grid_task.side_effect = fake_find

        _mark_storyboard_grid_batch_items_failed(task, "宫格生图超时")

        # 每个 scene 都应被查询一次
        self.assertEqual(MockBatchModel.find_running_by_grid_task.call_count, len(scene_ids))
        # 每个 item 都应被回写为 FAILED
        self.assertEqual(MockBatchModel.update.call_count, len(scene_ids))

        # 验证回写参数
        for call in MockBatchModel.update.call_args_list:
            _, kwargs = call
            self.assertEqual(
                kwargs["status"],
                StoryboardAutoGenerateConstants.BATCH_ITEM_STATUS_FAILED,
            )
            self.assertIn("宫格生图超时", kwargs["error_message"])

    @patch("model.storyboard_image_batch.StoryboardImageBatchItemModel")
    def test_skips_non_storyboard_grid_type(self, MockBatchModel):
        """非 STORYBOARD_FIRST_FRAME_GRID 类型不回写（避免误伤角色/场景宫格）。"""
        task = _make_task([1, 2], item_type=4)  # character_grid

        _mark_storyboard_grid_batch_items_failed(task, "error")

        MockBatchModel.find_running_by_grid_task.assert_not_called()
        MockBatchModel.update.assert_not_called()

    @patch("model.storyboard_image_batch.StoryboardImageBatchItemModel")
    def test_skips_scenes_without_running_item(self, MockBatchModel):
        """find_running_by_grid_task 返回 None 时跳过该 scene（不报错）。"""
        task = _make_task([415, 416])

        # 第一个 scene 有 RUNNING item，第二个没有
        MockBatchModel.find_running_by_grid_task.side_effect = [
            {"id": 1415, "extra_json": {}},
            None,
        ]

        _mark_storyboard_grid_batch_items_failed(task, "失败")

        self.assertEqual(MockBatchModel.update.call_count, 1)

    @patch("model.storyboard_image_batch.StoryboardImageBatchItemModel")
    def test_individual_scene_error_does_not_abort_others(self, MockBatchModel):
        """单个 scene 回写异常不影响其余 scene 的回写。"""
        task = _make_task([415, 416, 417])

        def fake_find(grid_task_id, scene_id):
            return {"id": 1000 + scene_id, "extra_json": {}}

        MockBatchModel.find_running_by_grid_task.side_effect = fake_find

        # 第二次 update 抛异常
        def fake_update(item_id, **kwargs):
            if item_id == 1416:
                raise RuntimeError("db error")

        MockBatchModel.update.side_effect = fake_update

        _mark_storyboard_grid_batch_items_failed(task, "失败")

        # 三个 scene 都被查询
        self.assertEqual(MockBatchModel.find_running_by_grid_task.call_count, 3)
        # 三个 scene 都尝试回写（即使第二个抛异常）
        self.assertEqual(MockBatchModel.update.call_count, 3)


class TestFailPendingGridSplitStepForTask(unittest.TestCase):
    """_fail_pending_grid_split_step_for_task 应把绑定 ai_tool 的 PENDING grid split step 标记 FAILED。"""

    def test_fails_pending_step_with_ai_tool_id(self):
        """project_id 可解析为 int 时，调用 fail_pending_grid_split_step。"""
        task = _make_task([415], project_id="1075")
        with patch("model.ai_tool_pipeline_steps.PipelineStepModel") as MockModel:
            _fail_pending_grid_split_step_for_task(task, "宫格生图失败")

            MockModel.fail_pending_grid_split_step.assert_called_once_with(1075, "宫格生图失败")

    def test_skips_non_storyboard_grid_type(self):
        """非 STORYBOARD_FIRST_FRAME_GRID 类型不回写 pipeline step。"""
        task = _make_task([1], item_type=4)
        with patch("model.ai_tool_pipeline_steps.PipelineStepModel") as MockModel:
            _fail_pending_grid_split_step_for_task(task, "error")

            MockModel.fail_pending_grid_split_step.assert_not_called()

    def test_invalid_project_id_does_not_raise(self):
        """project_id 不可解析时不抛异常、不回写（仅打日志）。"""
        task = _make_task([1], project_id=None)
        with patch("model.ai_tool_pipeline_steps.PipelineStepModel") as MockModel:
            _fail_pending_grid_split_step_for_task(task, "error")

            MockModel.fail_pending_grid_split_step.assert_not_called()

    def test_db_error_does_not_raise(self):
        """model 抛异常时被吞掉（避免影响上层失败回写流程）。"""
        task = _make_task([1], project_id="1075")
        with patch("model.ai_tool_pipeline_steps.PipelineStepModel") as MockModel:
            MockModel.fail_pending_grid_split_step.side_effect = RuntimeError("db down")
            # 不应抛异常
            _fail_pending_grid_split_step_for_task(task, "error")


class TestMarkBatchItemsFailedAlsoFailsPipelineStep(unittest.TestCase):
    """_mark_storyboard_grid_batch_items_failed 应在回写 batch item 后同步回写 pipeline step。"""

    @patch("model.ai_tool_pipeline_steps.PipelineStepModel")
    @patch("model.storyboard_image_batch.StoryboardImageBatchItemModel")
    def test_pipeline_step_failed_after_batch_items(self, MockBatchModel, MockStepModel):
        """超时/FAILED 路径调用该函数时，pipeline step 也被标记 FAILED。"""
        task = _make_task([415, 416], project_id="1075")
        MockBatchModel.find_running_by_grid_task.return_value = None  # 无 RUNNING item

        _mark_storyboard_grid_batch_items_failed(task, "宫格生图超时")

        # pipeline step 用正确的 ai_tool_id 回写
        MockStepModel.fail_pending_grid_split_step.assert_called_once_with(1075, "宫格生图超时")


class TestCleanupOrphanGridSplitSteps(unittest.TestCase):
    """_cleanup_orphan_grid_split_steps 应把 grid task 已失败但 step 仍 PENDING 的孤儿标记 FAILED。"""

    def _step(self, step_id):
        return SimpleNamespace(id=step_id)

    @patch("model.ai_tool_pipeline_steps.PipelineStepModel")
    def test_marks_orphans_failed(self, MockModel):
        """查到的孤儿 step 全部用 fail_steps_by_ids 标记 FAILED。"""
        MockModel.get_orphan_grid_split_steps.return_value = [self._step(72), self._step(91)]
        MockModel.fail_steps_by_ids.return_value = 2

        affected = _cleanup_orphan_grid_split_steps()

        self.assertEqual(affected, 2)
        # 传入的 step_ids 正确
        args, _ = MockModel.fail_steps_by_ids.call_args
        self.assertEqual(args[0], [72, 91])

    @patch("model.ai_tool_pipeline_steps.PipelineStepModel")
    def test_no_orphans_returns_zero(self, MockModel):
        """没有孤儿时不调用 fail_steps_by_ids。"""
        MockModel.get_orphan_grid_split_steps.return_value = []

        affected = _cleanup_orphan_grid_split_steps()

        self.assertEqual(affected, 0)
        MockModel.fail_steps_by_ids.assert_not_called()

    @patch("model.ai_tool_pipeline_steps.PipelineStepModel")
    def test_query_error_returns_zero(self, MockModel):
        """查询异常被吞掉，返回 0。"""
        MockModel.get_orphan_grid_split_steps.side_effect = RuntimeError("db down")

        affected = _cleanup_orphan_grid_split_steps()

        self.assertEqual(affected, 0)


if __name__ == "__main__":
    unittest.main()
