"""ImplementationRetryPipelineDriver 无事务顺序交接测试。"""
import asyncio
from unittest.mock import MagicMock, patch

from task.pipeline_drivers import implementation_retry_driver as module


def _step(params, step_order=0):
    step = MagicMock(id=80, ai_tool_id=10, step_order=step_order)
    step.get_params_dict.return_value = params
    return step


def test_retry_handoff_uses_attempt_number_and_queues_task_last():
    step = _step({
        'target_implementation': 'impl_c',
        'attempt_number': 3,
    }, step_order=0)
    ai_tool = MagicMock(id=10, implementation=1)
    calls = []

    with patch.object(module, 'get_implementation_id', return_value=3), \
            patch.object(module.AIToolsModel, 'update', side_effect=lambda *a, **k: calls.append('ai_tool')), \
            patch.object(module.TasksModel, 'update_by_task_id', side_effect=lambda *a, **k: calls.append('task_queued')), \
            patch.object(module, 'ImplementationAttemptModel', create=True) as attempts:
        attempts.create.side_effect = lambda *a, **k: calls.append('attempt')
        result = asyncio.run(module.ImplementationRetryPipelineDriver().execute(step, ai_tool))

    assert result['success'] is True
    assert 'step_finalized' not in result
    attempts.create.assert_called_once()
    assert attempts.create.call_args.kwargs['attempt_number'] == 3
    assert calls == ['ai_tool', 'attempt', 'task_queued']


def test_legacy_step_falls_back_to_step_order_attempt_number():
    step = _step({'target_implementation': 'impl_b'}, step_order=1)
    ai_tool = MagicMock(id=10, implementation=1)

    with patch.object(module, 'get_implementation_id', return_value=2), \
            patch.object(module.AIToolsModel, 'update'), \
            patch.object(module.TasksModel, 'update_by_task_id'), \
            patch.object(module, 'ImplementationAttemptModel', create=True) as attempts:
        result = asyncio.run(module.ImplementationRetryPipelineDriver().execute(step, ai_tool))

    assert result['success'] is True
    assert attempts.create.call_args.kwargs['attempt_number'] == 3


def test_ai_tool_update_failure_does_not_queue_task():
    step = _step({'target_implementation': 'impl_b', 'attempt_number': 2})
    ai_tool = MagicMock(id=10, implementation=1)

    with patch.object(module, 'get_implementation_id', return_value=2), \
            patch.object(module.AIToolsModel, 'update', side_effect=RuntimeError('db down')), \
            patch.object(module.TasksModel, 'update_by_task_id') as update_task:
        result = asyncio.run(module.ImplementationRetryPipelineDriver().execute(step, ai_tool))

    assert result['success'] is False
    update_task.assert_not_called()
