"""排队任务取消互斥（CAS）单元测试。

核心不变量：任务一旦被取消（status→CANCELLED），调度器/同步池/流水线
三处上游调用入口的抢占（条件 UPDATE）必然失败，绝不调用上游接口。
双向互斥由同一行上的条件更新保证（详见 docs/video/queued_task_cancel_design.md）。
"""
import asyncio
import unittest
from unittest.mock import MagicMock, patch

from config.constant import (
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_SYNC_QUEUED,
    AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
    AI_TOOL_STATUS_CANCELLED,
    AI_TOOL_CANCELLABLE_STATUSES,
    TASK_STATUS_CANCELLED,
)


class TestAIToolsTransitionStatus(unittest.TestCase):
    """transition_status 条件更新 SQL 正确性（互斥谓词必须落在 WHERE 里）。"""

    def _run(self, *args, **kwargs):
        from model import ai_tools as mod
        with patch.object(mod, "execute_update", return_value=1) as mock_exec:
            affected = mod.AIToolsModel.transition_status(*args, **kwargs)
        return affected, mock_exec

    def test_cancel_uses_in_clause_with_cancellable_statuses(self):
        affected, mock_exec = self._run(
            42, list(AI_TOOL_CANCELLABLE_STATUSES), AI_TOOL_STATUS_CANCELLED,
            message="任务已被用户取消",
        )
        self.assertEqual(affected, 1)
        sql, params = mock_exec.call_args[0]
        self.assertIn("WHERE id = %s AND status IN (", sql)
        self.assertNotIn("cancel_requested", sql)
        self.assertIn("status = %s", sql)
        # 参数顺序必须与占位符一致：SET(status,message) → WHERE id → IN(...)
        # （曾因 record_id 放末尾导致 WHERE id 绑定到 PENDING=0、永远 0 行命中，
        #   真实数据库复现发现；本断言用精确元组防止再次错序）
        self.assertEqual(
            params,
            (AI_TOOL_STATUS_CANCELLED, "任务已被用户取消", 42,
             AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_SYNC_QUEUED,
             AI_TOOL_STATUS_WAITING_PARAM_PREPARE),
        )

    def test_scheduler_preempt_single_from_status(self):
        affected, mock_exec = self._run(
            7, [AI_TOOL_STATUS_PENDING], AI_TOOL_STATUS_PROCESSING
        )
        self.assertEqual(affected, 1)
        sql, params = mock_exec.call_args[0]
        self.assertIn("WHERE id = %s AND status IN (%s)", sql)
        self.assertNotIn("cancel_requested", sql)
        self.assertEqual(params, (AI_TOOL_STATUS_PROCESSING, 7, AI_TOOL_STATUS_PENDING))

    def test_single_int_from_status_accepted(self):
        affected, _ = self._run(9, AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING)
        self.assertEqual(affected, 1)

    def test_block_if_cancel_requested_appends_predicate(self):
        _, mock_exec = self._run(
            7, [AI_TOOL_STATUS_PENDING], AI_TOOL_STATUS_PROCESSING,
            block_if_cancel_requested=True,
        )
        sql, params = mock_exec.call_args[0]
        self.assertIn("AND cancel_requested = 0", sql)
        self.assertNotIn("cancel_requested = 1", sql)
        self.assertEqual(params, (AI_TOOL_STATUS_PROCESSING, 7, AI_TOOL_STATUS_PENDING))

    def test_require_cancel_requested_appends_predicate(self):
        _, mock_exec = self._run(
            7, list(AI_TOOL_CANCELLABLE_STATUSES), AI_TOOL_STATUS_CANCELLED,
            require_cancel_requested=True,
        )
        sql, params = mock_exec.call_args[0]
        self.assertIn("AND cancel_requested = 1", sql)
        self.assertEqual(params[0], AI_TOOL_STATUS_CANCELLED)
        self.assertEqual(params[1], 7)

    def test_affected_zero_propagates(self):
        from model import ai_tools as mod
        with patch.object(mod, "execute_update", return_value=0):
            self.assertEqual(
                mod.AIToolsModel.transition_status(
                    5, [AI_TOOL_STATUS_PENDING], AI_TOOL_STATUS_CANCELLED
                ),
                0,
            )


class TestUpdateOnlyFieldsRejectsStatus(unittest.TestCase):
    """字段更新函数签名里没有 status，传入必须在碰数据库之前失败。"""

    def test_update_only_fields_rejects_status(self):
        from model.ai_tools import AIToolsModel
        with self.assertRaises(TypeError):
            AIToolsModel.update_only_fields(1, status=2, message="x")

    def test_update_only_fields_by_project_id_rejects_status(self):
        from model.ai_tools import AIToolsModel
        with self.assertRaises(TypeError):
            AIToolsModel.update_only_fields_by_project_id("p", status=2)

    def test_cdn_wrappers_reject_status_before_lookup(self):
        from model.ai_tools import AIToolsModel
        with self.assertRaises(TypeError):
            AIToolsModel.update_only_fields_with_cdn_sync(1, result_url="u", status=2)
        with self.assertRaises(TypeError):
            AIToolsModel.update_only_fields_by_project_id_with_cdn_sync("p", status=2)


class TestTasksTransitionStatus(unittest.TestCase):
    def test_sql_predicates(self):
        from model import tasks as mod
        with patch.object(mod, "execute_update", return_value=1) as mock_exec:
            affected = mod.TasksModel.transition_status_by_task_id(
                11, [0, 3, 4], TASK_STATUS_CANCELLED
            )
        self.assertEqual(affected, 1)
        sql, params = mock_exec.call_args[0]
        self.assertIn("UPDATE tasks SET status = %s", sql)
        self.assertIn("WHERE task_id = %s AND status IN (%s,%s,%s)", sql)
        self.assertEqual(params, (TASK_STATUS_CANCELLED, 11, 0, 3, 4))


class TestPipelineStepCancelMethods(unittest.TestCase):
    def test_try_update_status_sql(self):
        from model import ai_tool_pipeline_steps as mod
        with patch.object(mod, "execute_update", return_value=1) as mock_exec:
            affected = mod.PipelineStepModel.try_update_status(
                77, mod.PipelineStepStatus.PENDING, mod.PipelineStepStatus.PROCESSING
            )
        self.assertEqual(affected, 1)
        sql, params = mock_exec.call_args[0]
        self.assertIn("WHERE id = %s AND status = %s", sql)
        # 精确元组断言参数顺序：SET → WHERE id → WHERE status
        self.assertEqual(
            params,
            (mod.PipelineStepStatus.PROCESSING, 77, mod.PipelineStepStatus.PENDING),
        )

    def test_cancel_pending_steps_only_touches_pending(self):
        from model import ai_tool_pipeline_steps as mod
        with patch.object(mod, "execute_update", return_value=2) as mock_exec:
            affected = mod.PipelineStepModel.cancel_pending_steps_by_ai_tool(33)
        self.assertEqual(affected, 2)
        sql, params = mock_exec.call_args[0]
        self.assertIn("WHERE ai_tool_id = %s AND status = %s", sql)
        self.assertEqual(
            params[:1] + params[2:],
            (mod.PipelineStepStatus.CANCELLED, 33, mod.PipelineStepStatus.PENDING),
        )


class TestSyncWorkerCancelGuard(unittest.TestCase):
    """同步池 worker 执行前的 CAS 闸门：抢占失败绝不调用上游。"""

    def test_worker_skips_upstream_when_cas_rejected(self):
        from task import sync_task_executor as mod

        with patch("model.AIToolsModel") as mock_ai_tools:
            mock_ai_tools.transition_status.return_value = 0  # 已被取消
            with patch("task.visual_drivers.VideoDriverFactory") as mock_factory:
                result = mod._execute_sync_task(task_id=123, ai_tool_type=2)

        self.assertTrue(result.success)
        self.assertEqual(result.error_type, "CANCELLED")
        # 关键断言：驱动工厂从未被调用（没有创建驱动 → 不可能调用上游接口）
        mock_factory.create_driver_by_implementation.assert_not_called()
        mock_factory.create_driver_by_type.assert_not_called()

    def test_result_handler_keeps_cancelled_terminal_state(self):
        from task import sync_task_executor as mod

        executor = mod.SyncTaskExecutor.__new__(mod.SyncTaskExecutor)
        result = mod.SyncTaskResult(
            task_id=1, ai_tool_type=2, success=True, result_url=None,
            error="cancelled", error_type="CANCELLED",
        )
        with patch("model.AIToolsModel") as mock_ai_tools:
            executor._handle_task_result(result)
        # CANCELLED 结果：不读库不写库（连状态查询都不应发生）
        mock_ai_tools.update_with_cdn_sync.assert_not_called()
        mock_ai_tools.update.assert_not_called()


class TestPipelineDispatchCancelGuard(unittest.TestCase):
    """流水线分发前的步骤 CAS 闸门：抢占失败不执行 driver.execute。"""

    def _make_step(self):
        from model.ai_tool_pipeline_steps import PipelineStep
        return PipelineStep(
            id=55, ai_tool_id=9, stage='param_prepare',
            step_type='face_mask', status=0,
        )

    def test_dispatch_skips_when_step_cas_rejected(self):
        from task import pipeline_processor as mod

        step = self._make_step()
        with patch.object(mod.PipelineDriverFactory, "create_driver") as mock_create:
            mock_create.return_value = MagicMock()
            with patch.object(mod, "AIToolsModel") as mock_ai_tools:
                mock_ai_tools.get_by_id.return_value = MagicMock(
                    status=AI_TOOL_STATUS_WAITING_PARAM_PREPARE
                )
                with patch.object(mod.PipelineStepModel, "try_update_status", return_value=0):
                    ok = asyncio.run(mod.PipelineProcessor.dispatch_step(step))

        self.assertFalse(ok)
        mock_create.return_value.execute.assert_not_called()

    def test_dispatch_skips_when_ai_tool_cancelled(self):
        from task import pipeline_processor as mod

        step = self._make_step()
        with patch.object(mod.PipelineDriverFactory, "create_driver") as mock_create:
            mock_create.return_value = MagicMock()
            with patch.object(mod, "AIToolsModel") as mock_ai_tools:
                mock_ai_tools.get_by_id.return_value = MagicMock(
                    status=AI_TOOL_STATUS_CANCELLED
                )
                with patch.object(mod.PipelineStepModel, "try_update_status", return_value=1):
                    ok = asyncio.run(mod.PipelineProcessor.dispatch_step(step))

        self.assertFalse(ok)
        mock_create.return_value.execute.assert_not_called()


class TestFailureHandlerCancelGuard(unittest.TestCase):
    """统一失败入口：已取消的任务不被覆盖为 FAILED、不触发企业版重试。"""

    def test_failure_handler_skips_cancelled_task(self):
        from task import visual_task as mod

        with patch.object(mod, "_enterprise_failure_handler") as mock_enterprise:
            with patch.object(mod, "AIToolsModel") as mock_ai_tools:
                mock_ai_tools.get_by_id.return_value = MagicMock(
                    status=AI_TOOL_STATUS_CANCELLED
                )
                result = mod._handle_task_failure(
                    task_id=1, ai_tool_type=2, reason="x", user_id=3
                )

        self.assertTrue(result)
        mock_enterprise.assert_not_called()
        mock_ai_tools.update.assert_not_called()


class TestPipelineStageAdvanceCancelGuard(unittest.TestCase):
    """_check_pipeline_stage 推进回 PENDING 的取消互斥（rebase 冲突解决点）：
    CAS 4→0 抢占失败（任务已取消）时不写 tasks、不推进；返回值遵循
    PROCESS_RESULT_* 协议，防止外层误按失败退避重试。"""

    def _run_param_prepare_stage(self, steps, ai_status, transition_result):
        from task import visual_task as mod
        from task.pipeline_processor import PipelineProcessor
        from model.ai_tool_pipeline_steps import PipelineStepStatus

        ai_tool = MagicMock()
        ai_tool.id = 77
        completed_steps = [
            MagicMock(status=PipelineStepStatus.COMPLETED, step_type="x")
        ] if steps else []

        with patch.object(PipelineProcessor, "get_all_steps", return_value=completed_steps):
            with patch.object(PipelineProcessor, "apply_results") as mock_apply:
                with patch.object(mod.AIToolsModel, "get_by_id",
                                  return_value=MagicMock(status=ai_status)):
                    with patch.object(mod.AIToolsModel, "transition_status",
                                      return_value=transition_result) as mock_cas:
                        with patch.object(mod.TasksModel, "update_by_task_id") as mock_tasks:
                            result = mod._check_pipeline_stage(
                                ai_tool, mod.PipelineStage.PARAM_PREPARE
                            )
        return result, mock_cas, mock_tasks, mock_apply

    def test_no_steps_advance_blocked_when_cancelled(self):
        from task import visual_task as mod

        result, mock_cas, mock_tasks, _ = self._run_param_prepare_stage(
            steps=False, ai_status=None, transition_result=0
        )

        self.assertEqual(result, mod.PROCESS_RESULT_IN_FLIGHT)
        mock_cas.assert_called_once_with(
            77, [mod.AI_TOOL_STATUS_WAITING_PARAM_PREPARE], mod.AI_TOOL_STATUS_PENDING,
            block_if_cancel_requested=True,
        )
        mock_tasks.assert_not_called()

    def test_no_steps_advance_normal(self):
        from task import visual_task as mod

        result, _, mock_tasks, _ = self._run_param_prepare_stage(
            steps=False, ai_status=None, transition_result=1
        )

        self.assertEqual(result, mod.PROCESS_RESULT_IN_FLIGHT)
        mock_tasks.assert_called_once_with(77, status=mod.TASK_STATUS_QUEUED)

    def test_completed_cancelled_skips_apply_and_advance(self):
        from task import visual_task as mod

        result, mock_cas, mock_tasks, mock_apply = self._run_param_prepare_stage(
            steps=True, ai_status=mod.AI_TOOL_STATUS_CANCELLED, transition_result=0
        )

        self.assertTrue(result)  # 已处理（终态），外层不得退避重试
        mock_apply.assert_not_called()
        mock_cas.assert_not_called()
        mock_tasks.assert_not_called()

    def test_completed_cas_rejected_keeps_cancelled(self):
        from task import visual_task as mod

        result, mock_cas, mock_tasks, mock_apply = self._run_param_prepare_stage(
            steps=True, ai_status=mod.AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
            transition_result=0
        )

        self.assertTrue(result)
        mock_apply.assert_called_once()
        mock_cas.assert_called_once_with(
            77, [mod.AI_TOOL_STATUS_WAITING_PARAM_PREPARE], mod.AI_TOOL_STATUS_PENDING,
            block_if_cancel_requested=True,
        )
        mock_tasks.assert_not_called()

    def test_completed_normal_advances_to_pending(self):
        from task import visual_task as mod

        result, _, mock_tasks, _ = self._run_param_prepare_stage(
            steps=True, ai_status=mod.AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
            transition_result=1
        )

        self.assertEqual(result, mod.PROCESS_RESULT_IN_FLIGHT)
        mock_tasks.assert_called_once_with(77, status=mod.TASK_STATUS_QUEUED)

    def test_cancel_requested_commits_without_advance(self):
        from task import visual_task as mod
        from task.pipeline_processor import PipelineProcessor

        ai_tool = MagicMock()
        ai_tool.id = 77
        current = MagicMock(
            status=AI_TOOL_STATUS_WAITING_PARAM_PREPARE, cancel_requested=1,
        )
        with patch.object(PipelineProcessor, "get_all_steps", return_value=[]):
            with patch.object(PipelineProcessor, "apply_results") as mock_apply:
                with patch.object(mod.AIToolsModel, "get_by_id", return_value=current):
                    with patch.object(mod.AIToolsModel, "transition_status") as mock_cas:
                        with patch.object(mod.PipelineStepModel, "has_processing_for_ai_tool", return_value=False):
                            with patch.object(mod, "commit_deferred_cancel", return_value=True) as mock_commit:
                                result = mod._check_pipeline_stage(
                                    ai_tool, mod.PipelineStage.PARAM_PREPARE
                                )
        self.assertTrue(result)
        mock_apply.assert_not_called()
        mock_cas.assert_not_called()
        mock_commit.assert_called_once_with(77)

    def test_cancel_requested_waits_while_step_processing(self):
        from task import visual_task as mod

        ai_tool = MagicMock()
        ai_tool.id = 77
        current = MagicMock(
            status=AI_TOOL_STATUS_WAITING_PARAM_PREPARE, cancel_requested=1,
        )
        with patch.object(mod.AIToolsModel, "get_by_id", return_value=current):
            with patch.object(mod.PipelineStepModel, "has_processing_for_ai_tool", return_value=True):
                with patch.object(mod, "commit_deferred_cancel") as mock_commit:
                    result = mod._check_pipeline_stage(
                        ai_tool, mod.PipelineStage.PARAM_PREPARE
                    )
        self.assertFalse(result)
        mock_commit.assert_not_called()


class TestDeferredDispatchCancel(unittest.TestCase):
    """取消标识落下之后，dispatch_step 不得调用 driver.execute。"""

    def _make_step(self):
        from model.ai_tool_pipeline_steps import PipelineStep
        return PipelineStep(
            id=55, ai_tool_id=9, stage='param_prepare',
            step_type='face_mask', status=0,
        )

    def test_dispatch_skips_execute_when_cancel_requested_before_claim(self):
        from task import pipeline_processor as mod

        step = self._make_step()
        tool = MagicMock(status=AI_TOOL_STATUS_WAITING_PARAM_PREPARE, cancel_requested=1)
        with patch.object(mod.PipelineDriverFactory, "create_driver") as mock_create:
            mock_create.return_value = MagicMock()
            with patch.object(mod, "AIToolsModel") as mock_ai_tools:
                mock_ai_tools.get_by_id.return_value = tool
                with patch.object(mod.PipelineStepModel, "try_update_status", return_value=1):
                    with patch("task.queued_cancel.commit_deferred_cancel", return_value=True) as mock_commit:
                        ok = asyncio.run(mod.PipelineProcessor.dispatch_step(step))
        self.assertFalse(ok)
        mock_create.return_value.execute.assert_not_called()
        mock_commit.assert_called_once_with(9)

    def test_dispatch_aborts_after_step_cas_when_flag_lands(self):
        from task import pipeline_processor as mod
        from model.ai_tool_pipeline_steps import PipelineStepStatus

        step = self._make_step()
        before = MagicMock(status=AI_TOOL_STATUS_WAITING_PARAM_PREPARE, cancel_requested=0)
        after = MagicMock(status=AI_TOOL_STATUS_WAITING_PARAM_PREPARE, cancel_requested=1)
        with patch.object(mod.PipelineDriverFactory, "create_driver") as mock_create:
            mock_create.return_value = MagicMock()
            with patch.object(mod, "AIToolsModel") as mock_ai_tools:
                mock_ai_tools.get_by_id.side_effect = [before, after]
                with patch.object(mod.PipelineStepModel, "try_update_status", return_value=1) as mock_step:
                    with patch("task.queued_cancel.commit_deferred_cancel", return_value=True):
                        ok = asyncio.run(mod.PipelineProcessor.dispatch_step(step))
        self.assertFalse(ok)
        mock_create.return_value.execute.assert_not_called()
        mock_step.assert_any_call(
            55, PipelineStepStatus.PROCESSING, PipelineStepStatus.CANCELLED,
            error_message='任务已被用户取消',
        )


class TestCommitDeferredCancelIdleGuard(unittest.TestCase):
    def test_does_not_transition_while_step_processing(self):
        from task.queued_cancel import commit_deferred_cancel

        with patch(
            "model.ai_tool_pipeline_steps.PipelineStepModel.has_processing_for_ai_tool",
            return_value=True,
        ):
            with patch("model.ai_tools.AIToolsModel.transition_status") as mock_cas:
                ok = commit_deferred_cancel(9)
        self.assertFalse(ok)
        mock_cas.assert_not_called()

    def test_should_defer_only_for_param_prepare(self):
        from task.queued_cancel import should_defer_cancel

        preparing = MagicMock(status=AI_TOOL_STATUS_WAITING_PARAM_PREPARE, cancel_requested=0)
        pending = MagicMock(status=AI_TOOL_STATUS_PENDING, cancel_requested=0)
        flagged = MagicMock(status=AI_TOOL_STATUS_WAITING_PARAM_PREPARE, cancel_requested=1)
        self.assertTrue(should_defer_cancel(preparing, True))
        self.assertFalse(should_defer_cancel(preparing, False))
        self.assertFalse(should_defer_cancel(pending, True))
        self.assertTrue(should_defer_cancel(flagged, False))


if __name__ == "__main__":
    unittest.main()
