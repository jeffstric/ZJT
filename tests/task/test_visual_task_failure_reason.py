"""
visual_task 失败原因归一化单元测试
"""
import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock


_saved_modules = {
    name: sys.modules.get(name)
    for name in [
        'model',
        'model.runninghub_slots',
        'model.ai_tool_pipeline_steps',
        'model.ai_tools_log',
        'config.constant',
        'config.config_util',
        'perseids_server.client',
    ]
}

model_pkg = types.ModuleType('model')
model_pkg.TasksModel = MagicMock()
model_pkg.AIToolsModel = MagicMock()
model_pkg.RunningHubSlotsModel = MagicMock()
sys.modules['model'] = model_pkg

runninghub_slots = types.ModuleType('model.runninghub_slots')
runninghub_slots.RunningHubSlot = MagicMock()
runninghub_slots.RunningHubSlot.SOURCE_TASK = 'task'
sys.modules['model.runninghub_slots'] = runninghub_slots

pipeline_steps = types.ModuleType('model.ai_tool_pipeline_steps')
pipeline_steps.PipelineStepStatus = MagicMock()
pipeline_steps.PipelineStage = MagicMock()
pipeline_steps.PipelineStepType = MagicMock()
sys.modules['model.ai_tool_pipeline_steps'] = pipeline_steps

ai_tools_log = types.ModuleType('model.ai_tools_log')
ai_tools_log.AIToolsLogModel = MagicMock()
ai_tools_log.AIToolsLogEvent = MagicMock()
sys.modules['model.ai_tools_log'] = ai_tools_log

constant = types.ModuleType('config.constant')
constant.TASK_COMPUTING_POWER = {}
constant.TASK_TYPE_GENERATE_VIDEO = 'generate_video'
constant.AI_TOOL_STATUS_PENDING = 0
constant.AI_TOOL_STATUS_PROCESSING = 1
constant.AI_TOOL_STATUS_COMPLETED = 2
constant.AI_TOOL_STATUS_FAILED = -1
constant.AI_TOOL_STATUS_SYNC_QUEUED = 3
constant.AI_TOOL_STATUS_WAITING_PARAM_PREPARE = 4
constant.AI_TOOL_STATUS_WAITING_BEFORE_FINISH = 5
constant.TASK_STATUS_QUEUED = 0
constant.TASK_STATUS_PROCESSING = 1
constant.TASK_STATUS_COMPLETED = 2
constant.TASK_STATUS_FAILED = -1
constant.TASK_STATUS_SYNC_QUEUED = 3
constant.TASK_STATUS_WAITING_PARAM_PREPARE = 4
constant.TASK_STATUS_WAITING_BEFORE_FINISH = 5
constant.RUNNINGHUB_TASK_TYPES = []
constant.RUNNINGHUB_UPSTREAM_CONGEST_RETRY_DELAY_DEFAULT = 30
# f668 孤儿宽限：0 = 禁用（本测试只关注失败原因归一化，不涉及孤儿恢复）
constant.get_sync_orphan_grace_seconds = MagicMock(return_value=0)
sys.modules['config.constant'] = constant

config_util = types.ModuleType('config.config_util')
config_util.get_dynamic_config_value = MagicMock(return_value=False)
sys.modules['config.config_util'] = config_util

perseids_client = types.ModuleType('perseids_server.client')
perseids_client.make_perseids_request = MagicMock()
sys.modules['perseids_server.client'] = perseids_client

if 'task.visual_task' in sys.modules:
    importlib.reload(sys.modules['task.visual_task'])

from task.visual_task import _normalize_failure_reason

for _name, _saved in _saved_modules.items():
    if _saved is not None:
        sys.modules[_name] = _saved
    else:
        sys.modules.pop(_name, None)


class TestNormalizeFailureReason(unittest.TestCase):
    """测试外部 API 返回的失败原因可安全写入数据库"""

    def test_dict_error_uses_message_text(self):
        reason = {
            'code': 'task_failed',
            'message': '任务处理异常崩溃: Redis timeout'
        }

        self.assertEqual(
            _normalize_failure_reason(reason),
            '任务处理异常崩溃: Redis timeout'
        )

    def test_dict_without_message_serializes_to_json(self):
        reason = {'code': 'task_failed', 'detail': {'phase': 'query'}}

        self.assertEqual(
            _normalize_failure_reason(reason),
            '{"code": "task_failed", "detail": {"phase": "query"}}'
        )

    def test_none_uses_default_message(self):
        self.assertEqual(_normalize_failure_reason(None), '任务失败')


if __name__ == '__main__':
    unittest.main()
