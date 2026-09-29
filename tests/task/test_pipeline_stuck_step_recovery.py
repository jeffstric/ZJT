"""
卡死 PROCESSING 步骤回收的单元测试。

背景（生产事故 app.2026-09-14 起）：step 6759（h3_prompt_optimize）长期停留在
PROCESSING 且 async_task_id 为 NULL，调度器每 13s 刷一条 WARNING，所属 ai_tool 的
param_prepare 阶段永久挂起 15+ 天。

验证点：
1. _recover_stuck_processing_steps 会把超时步骤批量标记 FAILED 并触发阶段完成检查；
2. 无卡死步骤时不做任何写操作；
3. model 层新方法 get_stuck_processing_steps_without_async_task 的 SQL 参数正确
   （timeout 参数进 INTERVAL，不受时区影响）；
4. _process_single_step 对无 async_task_id 的步骤仅告警不修改状态（回收由专门入口负责）。
"""
import asyncio
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import config.constant as _const


def _make_step(step_id=6759, ai_tool_id=48161, stage='param_prepare',
               step_type='h3_prompt_optimize', updated_at=None):
    return SimpleNamespace(
        id=step_id,
        ai_tool_id=ai_tool_id,
        stage=stage,
        step_type=step_type,
        status=1,
        async_task_id=None,
        updated_at=updated_at or datetime(2026, 9, 14, 0, 0, 0),
        created_at=datetime(2026, 9, 14, 0, 00, 0),
    )


class TestRecoverStuckProcessingSteps(unittest.TestCase):
    """PipelineProcessor._recover_stuck_processing_steps 回收链路"""

    def _run(self, coro):
        return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)

    @patch('task.pipeline_processor.PipelineStepModel')
    @patch.object(_const.PipelineConfig, 'STUCK_PROCESSING_WITHOUT_ASYNC_TASK_TIMEOUT_SECONDS', 3600)
    def test_recovers_stuck_steps_and_checks_completion(self, MockStepModel):
        """超时步骤被批量置 FAILED，且对受影响 (ai_tool, stage) 触发阶段完成检查"""
        from task.pipeline_processor import PipelineProcessor

        stuck = [_make_step(6759, 48161, 'param_prepare'),
                 _make_step(6760, 48161, 'param_prepare'),
                 _make_step(6801, 48200, 'before_finish')]
        MockStepModel.get_stuck_processing_steps_without_async_task.return_value = stuck

        with patch.object(PipelineProcessor, '_check_ai_tool_stage_completion',
                          new=MagicMock()) as mock_check:
            recovered = self._run(PipelineProcessor._recover_stuck_processing_steps())

        self.assertEqual(recovered, 3)
        # 查询参数：超时阈值来自 PipelineConfig
        MockStepModel.get_stuck_processing_steps_without_async_task.assert_called_once_with(
            3600, limit=_const.PipelineConfig.STUCK_PROCESSING_RECOVER_LIMIT,
        )
        # 批量失败只调一次，覆盖全部步骤 ID
        fail_call = MockStepModel.fail_processing_steps_by_ids.call_args
        self.assertEqual(sorted(fail_call.args[0]), [6759, 6760, 6801])
        self.assertIn('步骤卡死回收', fail_call.kwargs['error_message'])
        # 阶段完成检查按 (ai_tool_id, stage) 去重：3 步骤 → 2 组
        checked = {c.args for c in mock_check.call_args_list}
        self.assertEqual(checked, {(48161, 'param_prepare'), (48200, 'before_finish')})

    @patch('task.pipeline_processor.PipelineStepModel')
    def test_no_stuck_steps_no_writes(self, MockStepModel):
        """无卡死步骤时不做任何写操作"""
        from task.pipeline_processor import PipelineProcessor

        MockStepModel.get_stuck_processing_steps_without_async_task.return_value = []
        recovered = self._run(PipelineProcessor._recover_stuck_processing_steps())
        self.assertEqual(recovered, 0)
        MockStepModel.fail_processing_steps_by_ids.assert_not_called()

    @patch('task.pipeline_processor.PipelineStepModel')
    def test_completion_check_error_does_not_break_recovery(self, MockStepModel):
        """单个 ai_tool 的阶段检查抛异常不影响回收结果"""
        from task.pipeline_processor import PipelineProcessor

        MockStepModel.get_stuck_processing_steps_without_async_task.return_value = [
            _make_step(6759, 48161, 'param_prepare'),
        ]
        with patch.object(PipelineProcessor, '_check_ai_tool_stage_completion',
                          side_effect=RuntimeError('boom')):
            recovered = self._run(PipelineProcessor._recover_stuck_processing_steps())
        self.assertEqual(recovered, 1)
        MockStepModel.fail_processing_steps_by_ids.assert_called_once()


class TestStuckStepModelSql(unittest.TestCase):
    """model 层卡死查询/批量失败的参数与幂等语义（mock execute 层）"""

    def test_get_stuck_steps_sql_uses_db_now(self):
        """超时判定走 DB NOW() - INTERVAL（不受应用时区影响）"""
        import model.ai_tool_pipeline_steps as m

        with patch.object(m, 'execute_query', return_value=[]) as mock_q:
            m.PipelineStepModel.get_stuck_processing_steps_without_async_task(3600, limit=20)
        sql = mock_q.call_args.args[0]
        args = mock_q.call_args.args[1]
        self.assertIn('NOW() - INTERVAL %s SECOND', sql)
        self.assertIn('async_task_id IS NULL', sql)
        self.assertEqual(args, (m.PipelineStepStatus.PROCESSING, 3600, 20))

    def test_fail_processing_steps_only_touches_processing_rows(self):
        """批量失败仅更新 status=PROCESSING 的行（幂等）"""
        import model.ai_tool_pipeline_steps as m

        with patch.object(m, 'execute_update', return_value=2) as mock_u:
            affected = m.PipelineStepModel.fail_processing_steps_by_ids([6759, 6801], '回收')
        sql = mock_u.call_args.args[0]
        self.assertIn('AND status = %s', sql)
        self.assertEqual(affected, 2)


class TestProcessSingleStepWarnOnly(unittest.TestCase):
    """_process_single_step 对无 async_task_id 步骤仅告警，不改状态（回收由专门入口负责）"""

    def test_warns_and_returns_without_update(self):
        from task.pipeline_processor import PipelineProcessor

        step = _make_step()
        with patch('task.pipeline_processor.PipelineStepModel') as MockStepModel, \
                patch('task.pipeline_processor.logger') as mock_logger:
            self._run_async(PipelineProcessor._process_single_step(step))
        MockStepModel.update_status.assert_not_called()
        mock_logger.warning.assert_called_once()
        self.assertIn('stuck_seconds', mock_logger.warning.call_args.args[0])

    def _run_async(self, coro):
        return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


if __name__ == '__main__':
    unittest.main()
