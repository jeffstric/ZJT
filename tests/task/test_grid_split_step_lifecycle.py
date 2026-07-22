"""
分镜首帧宫格 grid split step 生命周期测试。

覆盖宫格重试导致 grid_image_tasks.project_id 漂移后，step 仍能被正确 dispatch / fail / 清理。
核心断言：所有查找/回写/清理路径统一按 params.grid_task_id（grid 主键，稳定）关联，
不再依赖会漂移的 project_id == ai_tool_id 不变式。
"""
import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

# 只 mock database 层，保持 model 包真实导入（与 test_grid_image_task_batch_failure.py 一致）
_saved_database = sys.modules.get("model.database")
sys.modules["model.database"] = MagicMock()

for _mod in [
    "model.grid_image_tasks",
    "model.ai_tools",
    "model.storyboard_image_batch",
    "model.ai_tool_pipeline_steps",
    "task.grid_image_task",
]:
    if _mod in sys.modules:
        importlib.reload(sys.modules[_mod])

from model.ai_tool_pipeline_steps import (  # noqa: E402
    PipelineStepModel,
    PipelineStepStatus,
    PipelineStepType,
    PipelineStage,
)
from task.grid_image_task import (  # noqa: E402
    _dispatch_storyboard_first_frame_grid_split,
    _fail_pending_grid_split_step_for_task,
    _cleanup_orphan_grid_split_steps,
)

if _saved_database is not None:
    sys.modules["model.database"] = _saved_database
else:
    sys.modules.pop("model.database", None)


def _make_task(grid_task_id=10, project_id="29", item_type=8, grid_size=4):
    """构造一个 grid task mock。item_type=8 即 STORYBOARD_FIRST_FRAME_GRID。"""
    return SimpleNamespace(
        id=grid_task_id,
        task_key="grid:2:1:22",
        item_type=item_type,
        project_id=project_id,
        grid_layout=None,
        get_item_names_list=lambda: [],
        get_target_entity_ids_list=lambda: [],
    )


class TestGetPendingGridSplitStepByGridTask(unittest.TestCase):
    """get_pending_grid_split_step_by_grid_task 必须按 params.grid_task_id 查询，而非 ai_tool_id。"""

    @patch("model.ai_tool_pipeline_steps.execute_query")
    def test_queries_by_grid_task_id_not_ai_tool_id(self, mock_query):
        """SQL WHERE 必须用 JSON_EXTRACT(params,'$.grid_task_id')，不含 ai_tool_id 条件。"""
        mock_query.return_value = [{"id": 99, "ai_tool_id": 22, "step_type": PipelineStepType.STORYBOARD_FIRST_FRAME_GRID_SPLIT}]

        result = PipelineStepModel.get_pending_grid_split_step_by_grid_task(10)

        self.assertIsNotNone(result)
        sql_arg = mock_query.call_args[0][0]
        # 必须按 grid_task_id JSON 字段查询
        self.assertIn("JSON_EXTRACT(params, '$.grid_task_id')", sql_arg)
        # 不应再用 ai_tool_id 作为查询条件
        self.assertNotIn("WHERE ai_tool_id", sql_arg)
        # 参数第二个值应是 grid_task_id 的字符串形式
        params_arg = mock_query.call_args[0][1]
        self.assertEqual(params_arg[3], "10")

    @patch("model.ai_tool_pipeline_steps.execute_query")
    def test_returns_none_when_not_found(self, mock_query):
        mock_query.return_value = []
        result = PipelineStepModel.get_pending_grid_split_step_by_grid_task(999)
        self.assertIsNone(result)


class TestFailPendingGridSplitStepByGridTask(unittest.TestCase):
    """fail_pending_grid_split_step_by_grid_task 必须按 params.grid_task_id 回写 FAILED。"""

    @patch("model.ai_tool_pipeline_steps.execute_update")
    def test_updates_by_grid_task_id(self, mock_update):
        mock_update.return_value = 1
        affected = PipelineStepModel.fail_pending_grid_split_step_by_grid_task(10, "宫格失败")

        self.assertEqual(affected, 1)
        sql_arg = mock_update.call_args[0][0]
        self.assertIn("JSON_EXTRACT(params, '$.grid_task_id')", sql_arg)
        self.assertNotIn("WHERE ai_tool_id", sql_arg)
        params_arg = mock_update.call_args[0][1]
        # SET status 应为 FAILED
        self.assertEqual(params_arg[0], PipelineStepStatus.FAILED)
        # grid_task_id 参数（最后一个）
        self.assertEqual(params_arg[-1], "10")


class TestGetOrphanGridSplitStepsJoin(unittest.TestCase):
    """孤儿清理 JOIN 必须按 grid_image_tasks.id = params.grid_task_id 关联。"""

    @patch("model.ai_tool_pipeline_steps.execute_query")
    def test_join_uses_grid_task_id_not_project_id(self, mock_query):
        """JOIN 条件含 JSON_EXTRACT(params,'$.grid_task_id')，不再含 CAST(s.ai_tool_id AS CHAR)。"""
        mock_query.return_value = []
        PipelineStepModel.get_orphan_grid_split_steps(
            limit=50,
            grid_terminal_statuses=(-1, -2, -3, -4, 2),
        )

        sql_arg = mock_query.call_args[0][0]
        # 新 JOIN：按 grid 主键
        self.assertIn("g.id = CAST(JSON_UNQUOTE(JSON_EXTRACT(s.params", sql_arg)
        self.assertIn("grid_task_id", sql_arg)
        # 旧 JOIN（按 project_id == ai_tool_id）必须移除
        self.assertNotIn("g.project_id = CAST(s.ai_tool_id AS CHAR)", sql_arg)


class TestDispatchUsesGridTaskId(unittest.TestCase):
    """_dispatch_storyboard_first_frame_grid_split 必须按 task.id（grid 主键）查找预建 step。"""

    @patch("task.grid_image_task.asyncio")
    @patch("model.ai_tool_pipeline_steps.PipelineStepModel")
    @patch("task.grid_image_task.AIToolsModel")
    @patch("task.grid_image_task._build_storyboard_grid_cells")
    def test_dispatch_finds_prebuilt_step_by_grid_task_id(
        self, mock_cells, MockAITools, MockStepModel, mock_asyncio
    ):
        """
        宫格重试后 project_id 漂移（22 -> 29），但仍应按 grid_task_id=task.id=10
        找到预建 step，校准 params 后 dispatch，而非 fallback 新建。
        """
        mock_cells.return_value = [{"scene_id": 1, "grid_index": 0, "placeholder": False, "batch_item_id": None}]
        prebuilt_step = SimpleNamespace(id=88, ai_tool_id=22)  # 旧 ai_tool_id，但 step 存在
        MockStepModel.get_pending_grid_split_step_by_grid_task.return_value = prebuilt_step
        mock_asyncio.run.return_value = True

        # project_id=29（漂移后），但 task.id=10 是稳定主键
        task = _make_task(grid_task_id=10, project_id="29")
        result = _dispatch_storyboard_first_frame_grid_split(
            task, "http://img", "/path/grid.png", 4
        )

        self.assertTrue(result)
        # 必须用 task.id 查找，而非 project_id
        MockStepModel.get_pending_grid_split_step_by_grid_task.assert_called_once_with(10)
        # 找到预建 step 后必须校准 params（补充重试后的最新宫格图数据）
        MockStepModel.update_params.assert_called_once()
        update_args = MockStepModel.update_params.call_args[0]
        self.assertEqual(update_args[0], 88)  # step.id
        params = update_args[1]
        self.assertEqual(params["grid_image_path"], "/path/grid.png")
        self.assertEqual(params["grid_result_url"], "http://img")
        self.assertEqual(params["grid_task_id"], 10)
        # 不应 fallback 新建
        MockStepModel.create.assert_not_called()

    @patch("task.grid_image_task.asyncio")
    @patch("model.ai_tool_pipeline_steps.PipelineStepModel")
    @patch("task.grid_image_task.AIToolsModel")
    @patch("task.grid_image_task._build_storyboard_grid_cells")
    def test_dispatch_fallback_creates_when_no_prebuilt(
        self, mock_cells, MockAITools, MockStepModel, mock_asyncio
    ):
        """预建 step 不存在（如预建失败）时，fallback 新建并用 grid_task_id 关联。"""
        mock_cells.return_value = []
        MockStepModel.get_pending_grid_split_step_by_grid_task.return_value = None
        MockStepModel.create.return_value = 200
        fallback_step = SimpleNamespace(id=200, ai_tool_id=29)
        MockStepModel.get_by_id.return_value = fallback_step
        mock_asyncio.run.return_value = True

        task = _make_task(grid_task_id=10, project_id="29")
        result = _dispatch_storyboard_first_frame_grid_split(
            task, "http://img", "/path/grid.png", 4
        )

        self.assertTrue(result)
        MockStepModel.create.assert_called_once()
        create_kwargs = MockStepModel.create.call_args[1]
        # fallback params 必须带 grid_task_id（稳定主键）
        self.assertEqual(create_kwargs["params"]["grid_task_id"], 10)


class TestFailPathUsesGridTaskId(unittest.TestCase):
    """_fail_pending_grid_split_step_for_task 必须用 task.id（grid 主键）回写，不受 project_id 漂移影响。"""

    def test_uses_task_id_not_project_id(self):
        """project_id 已漂移为 8，但回写必须用 grid_task_id=5（task.id）。"""
        # grid_task_id=5，project_id=8（漂移后）
        task = _make_task(grid_task_id=5, project_id="8")
        with patch("model.ai_tool_pipeline_steps.PipelineStepModel") as MockModel:
            _fail_pending_grid_split_step_for_task(task, "宫格超时")

            MockModel.fail_pending_grid_split_step_by_grid_task.assert_called_once_with(5, "宫格超时")
            # 绝不能用旧方法（按 ai_tool_id）
            MockModel.fail_pending_grid_split_step.assert_not_called()


if __name__ == "__main__":
    unittest.main()
