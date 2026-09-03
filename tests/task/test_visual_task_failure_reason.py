"""
visual_task 失败原因归一化单元测试

依赖 stub 全部通过 tests/base/test_isolation.py 官方工具安装：
- with 块内即使 import 中断，离开时也必然恢复 sys.modules 与父包属性；
- purged_modules 保证 stub 绑定版 task.visual_task 不会驻留，
  后续测试重新 import 时按真实依赖加载。
"""
import unittest
from unittest.mock import MagicMock

from tests.base.test_isolation import module_stub, purged_modules, stub_modules

_runninghub_slot_mock = MagicMock()
_runninghub_slot_mock.SOURCE_TASK = 'task'

with purged_modules('task.visual_task'), stub_modules({
    'model': module_stub(
        'model',
        TasksModel=MagicMock(),
        AIToolsModel=MagicMock(),
        RunningHubSlotsModel=MagicMock(),
    ),
    'model.runninghub_slots': module_stub(
        'model.runninghub_slots',
        RunningHubSlot=_runninghub_slot_mock,
    ),
    'model.ai_tool_pipeline_steps': module_stub(
        'model.ai_tool_pipeline_steps',
        PipelineStepStatus=MagicMock(),
        PipelineStage=MagicMock(),
        PipelineStepType=MagicMock(),
    ),
    'model.ai_tools_log': module_stub(
        'model.ai_tools_log',
        AIToolsLogModel=MagicMock(),
        AIToolsLogEvent=MagicMock(),
    ),
    'config.constant': module_stub(
        'config.constant',
        TASK_COMPUTING_POWER={},
        TASK_TYPE_GENERATE_VIDEO='generate_video',
        AI_TOOL_STATUS_PENDING=0,
        AI_TOOL_STATUS_PROCESSING=1,
        AI_TOOL_STATUS_COMPLETED=2,
        AI_TOOL_STATUS_FAILED=-1,
        AI_TOOL_STATUS_SYNC_QUEUED=3,
        AI_TOOL_STATUS_WAITING_PARAM_PREPARE=4,
        AI_TOOL_STATUS_WAITING_BEFORE_FINISH=5,
        TASK_STATUS_QUEUED=0,
        TASK_STATUS_PROCESSING=1,
        TASK_STATUS_COMPLETED=2,
        TASK_STATUS_FAILED=-1,
        TASK_STATUS_SYNC_QUEUED=3,
        TASK_STATUS_WAITING_PARAM_PREPARE=4,
        TASK_STATUS_WAITING_BEFORE_FINISH=5,
        RUNNINGHUB_TASK_TYPES=[],
        RUNNINGHUB_UPSTREAM_CONGEST_RETRY_DELAY_DEFAULT=30,
        VIDEO_TASK_RETRY_DELAY_MAX_SECONDS=96,
        # f668 孤儿宽限：0 = 禁用（本测试只关注失败原因归一化，不涉及孤儿恢复）
        get_sync_orphan_grace_seconds=MagicMock(return_value=0),
    ),
    'config.config_util': module_stub(
        'config.config_util',
        get_dynamic_config_value=MagicMock(return_value=False),
    ),
    'perseids_server.client': module_stub(
        'perseids_server.client',
        make_perseids_request=MagicMock(),
    ),
}):
    from task.visual_task import _normalize_failure_reason, _resolve_submit_failure_reason


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


class TestResolveSubmitFailureReason(unittest.TestCase):
    """提交失败原因计算：SYSTEM 归类不得屏蔽内容审核违规信息"""

    def test_user_error_keeps_original(self):
        self.assertEqual(
            _resolve_submit_failure_reason('普通用户错误', 'USER'),
            '普通用户错误'
        )

    def test_system_error_shielded_by_default(self):
        self.assertEqual(
            _resolve_submit_failure_reason('Redis connection timeout', 'SYSTEM'),
            '服务异常，请联系技术支持'
        )

    def test_system_moderation_error_keeps_original(self):
        error = (
            'Your request was rejected by the safety system. '
            'safety_violations=[sexual]. (request id: xxx)'
        )
        self.assertEqual(
            _resolve_submit_failure_reason(error, 'SYSTEM'),
            error
        )

    def test_system_friendly_message_kept(self):
        error = '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试'
        self.assertEqual(
            _resolve_submit_failure_reason(error, 'SYSTEM'),
            error
        )

    def test_none_error_shielded(self):
        self.assertEqual(
            _resolve_submit_failure_reason(None, 'SYSTEM'),
            '服务异常，请联系技术支持'
        )


if __name__ == '__main__':
    unittest.main()
