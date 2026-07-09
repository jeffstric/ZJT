"""
grid_image_task 模块的单元测试。

重点验证：当分镜首帧宫格任务（item_type=STORYBOARD_FIRST_FRAME_GRID）进入终态失败
（超时 / FAILED / 异常）时，_mark_storyboard_grid_batch_items_failed 能正确把关联的
storyboard_image_batch_item 从 RUNNING 回写为 FAILED，避免 batch item 永久卡死。
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
from task.grid_image_task import _mark_storyboard_grid_batch_items_failed  # noqa: E402

if _saved_database is not None:
    sys.modules["model.database"] = _saved_database
else:
    sys.modules.pop("model.database", None)


def _make_task(scene_ids, grid_task_id=454, item_type=8):
    """构造一个 grid task mock。item_type=8 即 STORYBOARD_FIRST_FRAME_GRID。"""
    return SimpleNamespace(
        id=grid_task_id,
        task_key="grid:1:2:1075",
        item_type=item_type,
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


if __name__ == "__main__":
    unittest.main()
