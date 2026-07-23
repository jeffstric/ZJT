"""
分镜首帧宫格 grid split step 生命周期测试。

覆盖宫格重试导致 grid_image_tasks.project_id 漂移后，step 仍能被正确 dispatch / fail / 清理。
核心断言：所有查找/回写/清理路径统一按 params.grid_task_id（grid 主键，稳定）关联，
不再依赖会漂移的 project_id == ai_tool_id 不变式。

隔离方式：全部使用 patch 装饰器在测试方法级别隔离，不修改全局 sys.modules，
避免污染同进程后续测试。被测函数 _dispatch_ 内部通过 `from model... import` 局部导入，
因此 patch 目标用 `model.ai_tool_pipeline_steps.PipelineStepModel` 等真实模块路径。
"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_task(grid_task_id=10, project_id="29", item_type=8, grid_size=4):
    """构造一个 grid task mock。item_type=8 即 STORYBOARD_FIRST_FRAME_GRID。

    project_id 默认 "29" 模拟宫格重试后漂移的新 ai_tool_id（原始为 22）。
    """
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
        from model.ai_tool_pipeline_steps import PipelineStepModel
        mock_query.return_value = [{"id": 99, "ai_tool_id": 22}]

        result = PipelineStepModel.get_pending_grid_split_step_by_grid_task(10)

        self.assertIsNotNone(result)
        sql_arg = mock_query.call_args[0][0]
        self.assertIn("JSON_EXTRACT(params, '$.grid_task_id')", sql_arg)
        self.assertNotIn("WHERE ai_tool_id", sql_arg)
        params_arg = mock_query.call_args[0][1]
        self.assertEqual(params_arg[3], "10")

    @patch("model.ai_tool_pipeline_steps.execute_query")
    def test_returns_none_when_not_found(self, mock_query):
        from model.ai_tool_pipeline_steps import PipelineStepModel
        mock_query.return_value = []
        self.assertIsNone(PipelineStepModel.get_pending_grid_split_step_by_grid_task(999))


class TestFailPendingGridSplitStepByGridTask(unittest.TestCase):
    """fail_pending_grid_split_step_by_grid_task 必须按 params.grid_task_id 回写 FAILED。"""

    @patch("model.ai_tool_pipeline_steps.execute_update")
    def test_updates_by_grid_task_id(self, mock_update):
        from model.ai_tool_pipeline_steps import PipelineStepModel, PipelineStepStatus
        mock_update.return_value = 1
        affected = PipelineStepModel.fail_pending_grid_split_step_by_grid_task(10, "宫格失败")

        self.assertEqual(affected, 1)
        sql_arg = mock_update.call_args[0][0]
        self.assertIn("JSON_EXTRACT(params, '$.grid_task_id')", sql_arg)
        self.assertNotIn("WHERE ai_tool_id", sql_arg)
        params_arg = mock_update.call_args[0][1]
        self.assertEqual(params_arg[0], PipelineStepStatus.FAILED)
        self.assertEqual(params_arg[-1], "10")


class TestGetOrphanGridSplitStepsJoin(unittest.TestCase):
    """孤儿清理 JOIN 必须按 grid_image_tasks.id = params.grid_task_id 关联。"""

    @patch("model.ai_tool_pipeline_steps.execute_query")
    def test_join_uses_grid_task_id_not_project_id(self, mock_query):
        """JOIN 条件含 JSON_EXTRACT(params,'$.grid_task_id')，不再含 CAST(s.ai_tool_id AS CHAR)。"""
        from model.ai_tool_pipeline_steps import PipelineStepModel
        mock_query.return_value = []
        PipelineStepModel.get_orphan_grid_split_steps(
            limit=50,
            grid_terminal_statuses=(-1, -2, -3, -4, 2),
        )

        sql_arg = mock_query.call_args[0][0]
        self.assertIn("g.id = CAST(JSON_UNQUOTE(JSON_EXTRACT(s.params", sql_arg)
        self.assertIn("grid_task_id", sql_arg)
        self.assertNotIn("g.project_id = CAST(s.ai_tool_id AS CHAR)", sql_arg)


class TestUpdateParamsAtomicWithAiToolId(unittest.TestCase):
    """update_params 传入 ai_tool_id 时必须单条 UPDATE 原子更新两个字段。"""

    @patch("model.ai_tool_pipeline_steps.execute_update")
    def test_updates_params_and_ai_tool_id_atomically(self, mock_update):
        from model.ai_tool_pipeline_steps import PipelineStepModel
        mock_update.return_value = 1
        PipelineStepModel.update_params(88, {"grid_task_id": 10}, ai_tool_id=29)

        sql_arg = mock_update.call_args[0][0]
        # 单条 UPDATE 同时含 params 和 ai_tool_id
        self.assertIn("SET params = %s, ai_tool_id = %s", sql_arg)
        params_arg = mock_update.call_args[0][1]
        self.assertEqual(params_arg[1], 29)  # ai_tool_id

    @patch("model.ai_tool_pipeline_steps.execute_update")
    def test_updates_params_only_when_no_ai_tool_id(self, mock_update):
        from model.ai_tool_pipeline_steps import PipelineStepModel
        mock_update.return_value = 1
        PipelineStepModel.update_params(88, {"grid_task_id": 10})

        sql_arg = mock_update.call_args[0][0]
        self.assertNotIn("ai_tool_id", sql_arg)


class TestDispatchUsesGridTaskId(unittest.TestCase):
    """_dispatch_ 必须按 task.id 查找预建 step，并校正 params+ai_tool_id 后重读再 dispatch。"""

    def test_dispatch_calibrates_and_rereads_step_before_dispatch(self):
        """
        P1 核心验证：宫格重试后 project_id 漂移（22 -> 29），预建 step.ai_tool_id=22。
        _dispatch_ 必须：
        1. 按 grid_task_id 找到预建 step；
        2. 用当前 task.project_id=29 原子更新 params + ai_tool_id；
        3. 重新读取 step（get_by_id）拿到最新对象；
        4. dispatch 重读后的 step（ai_tool_id=29，params 含最新宫格图）。
        绝不能 dispatch 原始内存对象（ai_tool_id=22，params 缺图）。
        """
        from task.grid_image_task import _dispatch_storyboard_first_frame_grid_split
        from task.pipeline_processor import PipelineProcessor

        # 预建 step 内存对象：ai_tool_id=22（旧），模拟数据库旧记录
        prebuilt_step = SimpleNamespace(id=88, ai_tool_id=22)
        # 重读后的 step：ai_tool_id 已校正为 29
        reread_step = SimpleNamespace(id=88, ai_tool_id=29)

        dispatched = {}

        async def fake_dispatch(step):
            dispatched["step"] = step
            return True

        with patch("task.grid_image_task.AIToolsModel"), \
             patch("model.ai_tool_pipeline_steps.PipelineStepModel") as MockStepModel, \
             patch("task.grid_image_task._build_storyboard_grid_cells", return_value=[]), \
             patch.object(PipelineProcessor, "dispatch_step", side_effect=fake_dispatch):
            MockStepModel.get_pending_grid_split_step_by_grid_task.return_value = prebuilt_step
            # get_by_id 返回重读后的 step（ai_tool_id=29）
            MockStepModel.get_by_id.return_value = reread_step

            task = _make_task(grid_task_id=10, project_id="29")
            result = _dispatch_storyboard_first_frame_grid_split(
                task, "http://new-img", "/path/new-grid.png", 4
            )

            self.assertTrue(result)
            # 1. 按 grid_task_id 查找（用 task.id=10，而非 project_id）
            MockStepModel.get_pending_grid_split_step_by_grid_task.assert_called_once_with(10)
            # 2. update_params 必须传入 ai_tool_id=29（校正漂移），不只是 params
            MockStepModel.update_params.assert_called_once()
            up_args, up_kwargs = MockStepModel.update_params.call_args
            self.assertEqual(up_args[0], 88)  # step.id
            self.assertEqual(up_kwargs.get("ai_tool_id"), 29)
            self.assertEqual(up_args[1]["grid_image_path"], "/path/new-grid.png")
            self.assertEqual(up_args[1]["grid_result_url"], "http://new-img")
            # 3. 必须重新读取 step（get_by_id），不能直接 dispatch 原始 prebuilt_step
            MockStepModel.get_by_id.assert_called_once_with(88)
            # 4. dispatch 的是重读后的 step（ai_tool_id=29），不是 prebuilt（ai_tool_id=22）
            self.assertIs(dispatched["step"], reread_step)
            self.assertEqual(dispatched["step"].ai_tool_id, 29)

    def test_dispatch_fallback_creates_when_no_prebuilt(self):
        """预建 step 不存在时，fallback 新建并用当前 project_id 作为 ai_tool_id。"""
        from task.grid_image_task import _dispatch_storyboard_first_frame_grid_split
        from task.pipeline_processor import PipelineProcessor

        async def fake_dispatch(step):
            return True

        with patch("task.grid_image_task.AIToolsModel"), \
             patch("model.ai_tool_pipeline_steps.PipelineStepModel") as MockStepModel, \
             patch("task.grid_image_task._build_storyboard_grid_cells", return_value=[]), \
             patch.object(PipelineProcessor, "dispatch_step", side_effect=fake_dispatch):
            MockStepModel.get_pending_grid_split_step_by_grid_task.return_value = None
            MockStepModel.create.return_value = 200
            fallback_step = SimpleNamespace(id=200, ai_tool_id=29)
            MockStepModel.get_by_id.return_value = fallback_step

            task = _make_task(grid_task_id=10, project_id="29")
            result = _dispatch_storyboard_first_frame_grid_split(
                task, "http://img", "/path/grid.png", 4
            )

            self.assertTrue(result)
            MockStepModel.create.assert_called_once()
            create_kwargs = MockStepModel.create.call_args[1]
            self.assertEqual(create_kwargs["params"]["grid_task_id"], 10)
            self.assertEqual(create_kwargs["ai_tool_id"], 29)


class TestDispatchDrivesCorrectAiToolAndParams(unittest.TestCase):
    """
    P1 端到端验证：通过真实 PipelineProcessor.dispatch_step 调用链，
    断言 driver 收到的 ai_tool_id 和 params 是重试后的最新值，而非旧值。

    用 asyncio.run 真实驱动 dispatch_step（patch 掉 driver.execute 和 AIToolsModel.get_by_id），
    消除"mock asyncio.run 掩盖 P1"的问题。
    """

    def test_driver_receives_calibrated_step(self):
        from task.grid_image_task import _dispatch_storyboard_first_frame_grid_split
        from task.pipeline_processor import PipelineProcessor

        # 重读后的 step：params 含最新宫格图，ai_tool_id=29
        reread_step = MagicMock()
        reread_step.id = 88
        reread_step.ai_tool_id = 29
        reread_step.stage = "before_finish"
        reread_step.step_type = "storyboard_first_frame_grid_split"
        reread_step.get_params_dict.return_value = {
            "grid_task_id": 10,
            "grid_image_path": "/path/new-grid.png",
            "grid_result_url": "http://new-img",
            "grid_size": 4,
        }

        captured = {}

        async def fake_dispatch(step):
            # 捕获真实传给 dispatch_step 的 step 对象
            captured["step"] = step
            captured["ai_tool_id"] = step.ai_tool_id
            captured["params"] = step.get_params_dict()
            return True

        with patch("task.grid_image_task.AIToolsModel"), \
             patch("model.ai_tool_pipeline_steps.PipelineStepModel") as MockStepModel, \
             patch("task.grid_image_task._build_storyboard_grid_cells", return_value=[]), \
             patch.object(PipelineProcessor, "dispatch_step", side_effect=fake_dispatch):
            MockStepModel.get_pending_grid_split_step_by_grid_task.return_value = SimpleNamespace(id=88, ai_tool_id=22)
            MockStepModel.get_by_id.return_value = reread_step

            task = _make_task(grid_task_id=10, project_id="29")
            result = _dispatch_storyboard_first_frame_grid_split(
                task, "http://new-img", "/path/new-grid.png", 4
            )

            self.assertTrue(result)
            # 关键断言：dispatch 收到的是校正后的 step，ai_tool_id=29（非旧值22）
            self.assertEqual(captured["ai_tool_id"], 29)
            self.assertEqual(captured["params"]["grid_image_path"], "/path/new-grid.png")
            self.assertEqual(captured["params"]["grid_result_url"], "http://new-img")


class TestFailPathUsesGridTaskId(unittest.TestCase):
    """_fail_pending_grid_split_step_for_task 必须用 task.id（grid 主键）回写，不受 project_id 漂移影响。"""

    def test_uses_task_id_not_project_id(self):
        """project_id 已漂移为 8，但回写必须用 grid_task_id=5（task.id）。"""
        from task.grid_image_task import _fail_pending_grid_split_step_for_task
        # grid_task_id=5，project_id=8（漂移后）
        task = _make_task(grid_task_id=5, project_id="8")
        with patch("model.ai_tool_pipeline_steps.PipelineStepModel") as MockModel:
            _fail_pending_grid_split_step_for_task(task, "宫格超时")

            MockModel.fail_pending_grid_split_step_by_grid_task.assert_called_once_with(5, "宫格超时")
            MockModel.fail_pending_grid_split_step.assert_not_called()


if __name__ == "__main__":
    unittest.main()
