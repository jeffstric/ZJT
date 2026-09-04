"""
visual_task 调度退避封顶单元测试

背景：RUNNING 轮询与失败重试共用 calculate_next_retry_delay 的指数退避。
360s 封顶时代，上游任务完成到被调度器发现之间的空窗最坏可达数分钟
（实测 Task 104 成片 19:55 跑完、19:57:35 才被发现），分镜长时间停在「生成中」。
封顶降为 VIDEO_TASK_RETRY_DELAY_MAX_SECONDS=96 后，完成发现延迟 ≤96s。

依赖 stub 全部通过 tests/base/test_isolation.py 官方工具安装
（模式同 test_visual_task_failure_reason.py）。
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
        AI_TOOL_STATUS_DOWNLOADING=6,
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
    from task.visual_task import calculate_next_retry_delay


class TestRetryDelayCap(unittest.TestCase):
    """退避斜坡 3*2^(n-1) 保持不变，封顶 96 秒"""

    def test_ramp_preserved(self):
        self.assertEqual(calculate_next_retry_delay(1), 3)
        self.assertEqual(calculate_next_retry_delay(2), 6)
        self.assertEqual(calculate_next_retry_delay(3), 12)
        self.assertEqual(calculate_next_retry_delay(4), 24)
        self.assertEqual(calculate_next_retry_delay(5), 48)

    def test_capped_at_96(self):
        # 斜坡第 6 次恰好到 96，之后不再增长（旧封顶 360 时代第 7 次为 192）
        self.assertEqual(calculate_next_retry_delay(6), 96)
        self.assertEqual(calculate_next_retry_delay(7), 96)
        self.assertEqual(calculate_next_retry_delay(20), 96)
        self.assertEqual(calculate_next_retry_delay(100), 96)

    def test_real_constant_value(self):
        # 真实常量（不经 stub）：防止误改回 360 级别
        from config.constant import VIDEO_TASK_RETRY_DELAY_MAX_SECONDS
        self.assertEqual(VIDEO_TASK_RETRY_DELAY_MAX_SECONDS, 96)


if __name__ == '__main__':
    unittest.main()
