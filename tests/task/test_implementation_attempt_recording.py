"""
visual_task 首次实现方 attempt 写入逻辑单元测试。

覆盖：画布创建时已预写 implementation 时，仍应写入 attempt_number=1；
已有 attempt（重试路径）时不重复写入。
"""
import asyncio
import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


_STUB_NAMES = [
    'model',
    'model.runninghub_slots',
    'model.ai_tool_pipeline_steps',
    'model.ai_tools_log',
    'model.ai_tools',
    'model.tasks',
    'model.implementation_attempts',
    'config.constant',
    'config.config_util',
    'config.unified_config',
    'perseids_server.client',
    'task.visual_drivers',
    'task.visual_drivers.driver_factory',
    'task.pipeline_processor',
    'task.sync_task_executor',
    'task.mock_interceptor',
    'utils.media_cache',
    'utils.file_storage',
]


def _install_module_stubs():
    saved = {name: sys.modules.get(name) for name in _STUB_NAMES}

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
    # visual_task 顶层 from model.ai_tool_pipeline_steps import PipelineStage, ...
    pipeline_steps.PipelineStage.PARAM_PREPARE = 'param_prepare'
    pipeline_steps.PipelineStage.BEFORE_FINISH = 'before_finish'
    sys.modules['model.ai_tool_pipeline_steps'] = pipeline_steps

    ai_tools_log = types.ModuleType('model.ai_tools_log')
    ai_tools_log.AIToolsLogModel = MagicMock()
    ai_tools_log.AIToolsLogEvent = MagicMock()
    sys.modules['model.ai_tools_log'] = ai_tools_log

    ai_tools = types.ModuleType('model.ai_tools')
    ai_tools.AIToolsModel = model_pkg.AIToolsModel
    sys.modules['model.ai_tools'] = ai_tools

    tasks = types.ModuleType('model.tasks')
    tasks.TasksModel = model_pkg.TasksModel
    sys.modules['model.tasks'] = tasks

    attempts = types.ModuleType('model.implementation_attempts')
    attempts.ImplementationAttemptModel = MagicMock()
    attempts.ATTEMPT_STATUS_SUCCESS = 2
    attempts.ATTEMPT_STATUS_FAILED = -1
    sys.modules['model.implementation_attempts'] = attempts

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
    # f668 孤儿宽限：0 = 禁用（本测试只关注 attempt 写入，不涉及孤儿恢复）
    constant.get_sync_orphan_grace_seconds = MagicMock(return_value=0)
    sys.modules['config.constant'] = constant

    config_util = types.ModuleType('config.config_util')
    config_util.get_dynamic_config_value = MagicMock(return_value=False)
    sys.modules['config.config_util'] = config_util

    unified = types.ModuleType('config.unified_config')
    unified.UnifiedConfigRegistry = MagicMock()
    unified.get_implementation_id = MagicMock(return_value=17)
    unified.get_implementation_name = MagicMock(return_value='ltx2.3_runninghub_v1')
    sys.modules['config.unified_config'] = unified

    perseids_client = types.ModuleType('perseids_server.client')
    perseids_client.make_perseids_request = MagicMock()
    sys.modules['perseids_server.client'] = perseids_client

    factory = MagicMock()
    visual_drivers = types.ModuleType('task.visual_drivers')
    visual_drivers.VideoDriverFactory = factory
    sys.modules['task.visual_drivers'] = visual_drivers
    factory_mod = types.ModuleType('task.visual_drivers.driver_factory')
    factory_mod.VideoDriverFactory = factory
    sys.modules['task.visual_drivers.driver_factory'] = factory_mod

    pipeline_mod = types.ModuleType('task.pipeline_processor')
    pipeline_mod.PipelineProcessor = MagicMock()
    pipeline_mod.PipelineProcessor.get_pending_steps.return_value = []
    sys.modules['task.pipeline_processor'] = pipeline_mod

    sync_exec = types.ModuleType('task.sync_task_executor')
    sync_exec.get_sync_task_executor = MagicMock()
    sys.modules['task.sync_task_executor'] = sync_exec

    mock_interceptor = types.ModuleType('task.mock_interceptor')
    mock_interceptor.is_mock_enabled = MagicMock(return_value=False)
    mock_interceptor.visual_async_submit_result = MagicMock()
    sys.modules['task.mock_interceptor'] = mock_interceptor

    media_cache = types.ModuleType('utils.media_cache')
    media_cache.download_and_cache = MagicMock()
    sys.modules['utils.media_cache'] = media_cache

    file_storage = types.ModuleType('utils.file_storage')
    sys.modules['utils.file_storage'] = file_storage

    return saved, factory, attempts, unified, model_pkg, pipeline_mod


class TestImplementationAttemptRecording(unittest.TestCase):
    """_submit_new_task 首次 attempt 写入条件"""

    @classmethod
    def setUpClass(cls):
        (
            cls._saved,
            cls.factory,
            cls.attempts_mod,
            cls.unified,
            cls.model_pkg,
            cls.pipeline_mod,
        ) = _install_module_stubs()
        if 'task.visual_task' in sys.modules:
            importlib.reload(sys.modules['task.visual_task'])
        else:
            importlib.import_module('task.visual_task')
        cls.visual_task = sys.modules['task.visual_task']

    @classmethod
    def tearDownClass(cls):
        for name, mod in cls._saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        sys.modules.pop('task.visual_task', None)

    def setUp(self):
        self.AIToolsModel = self.model_pkg.AIToolsModel
        self.TasksModel = self.model_pkg.TasksModel
        self.AttemptModel = self.attempts_mod.ImplementationAttemptModel

        self.AIToolsModel.reset_mock()
        self.TasksModel.reset_mock()
        self.AttemptModel.reset_mock()
        self.factory.reset_mock()
        self.unified.get_implementation_id.reset_mock()
        self.unified.get_implementation_name.reset_mock()
        self.pipeline_mod.PipelineProcessor.reset_mock()
        self.pipeline_mod.PipelineProcessor.get_pending_steps.return_value = []

        mock_driver = MagicMock()
        mock_driver.driver_name = 'ltx2.3_runninghub_v1'
        mock_driver.submit_task.return_value = {
            'success': True,
            'project_id': 'proj-ltx-1',
        }
        self.factory.create_driver_by_implementation.return_value = mock_driver
        self.factory.create_driver_by_type.return_value = mock_driver
        self.factory.get_implementation_for_user.return_value = 'ltx2.3_runninghub_v1'

        impl_config = MagicMock()
        impl_config.sync_mode = False
        self.unified.UnifiedConfigRegistry.get_implementation.return_value = impl_config
        self.unified.get_implementation_id.return_value = 17
        self.unified.get_implementation_name.return_value = 'ltx2.3_runninghub_v1'

        # 模块内 from-import 的绑定需对齐 stub
        self.visual_task.AIToolsModel = self.AIToolsModel
        self.visual_task.TasksModel = self.TasksModel
        self.visual_task.AIToolsLogModel = MagicMock()
        self.visual_task.AIToolsLogEvent = MagicMock()

    def _make_ai_tool(self, *, implementation=17):
        tool = MagicMock()
        tool.id = 9001
        tool.type = 20
        tool.user_id = 42
        tool.implementation = implementation
        tool.prompt = 'test'
        tool.image_path = None
        tool.ratio = '9:16'
        tool.duration = 5
        tool.extra_config = None
        tool.reference_images = None
        tool.audio_path = None
        tool.video_path = None
        tool.project_id = None
        tool.status = 0
        tool.message = None
        return tool

    def _run_submit(self, ai_tool):
        return asyncio.run(self.visual_task._submit_new_task(ai_tool))

    def test_create_attempt_when_implementation_preset(self):
        """画布预写 implementation 后，首次 submit 仍应 create attempt#1"""
        self.AttemptModel.get_attempted_implementations.return_value = set()
        self.AttemptModel.create.return_value = 1

        result = self._run_submit(self._make_ai_tool(implementation=17))

        self.assertTrue(result)
        self.AttemptModel.get_attempted_implementations.assert_called_with(9001)
        self.AttemptModel.create.assert_called_once()
        call_kwargs = self.AttemptModel.create.call_args.kwargs
        self.assertEqual(call_kwargs['ai_tool_id'], 9001)
        self.assertEqual(call_kwargs['implementation'], 17)
        self.assertEqual(call_kwargs['attempt_number'], 1)
        self.assertEqual(call_kwargs['status'], 0)

    def test_skip_create_when_attempts_already_exist(self):
        """重试路径已有 attempt 时，不再 create attempt#1"""
        self.AttemptModel.get_attempted_implementations.return_value = {17}

        result = self._run_submit(self._make_ai_tool(implementation=17))

        self.assertTrue(result)
        self.AttemptModel.get_attempted_implementations.assert_called_with(9001)
        self.AttemptModel.create.assert_not_called()

    def test_create_attempt_when_implementation_zero(self):
        """implementation=0 时按用户偏好解析后仍写 attempt#1"""
        self.AttemptModel.get_attempted_implementations.return_value = set()
        self.AttemptModel.create.return_value = 1
        self.factory.create_driver_by_implementation.return_value = None
        self.unified.get_implementation_name.return_value = 'unknown'

        result = self._run_submit(self._make_ai_tool(implementation=0))

        self.assertTrue(result)
        self.AttemptModel.create.assert_called_once()
        call_kwargs = self.AttemptModel.create.call_args.kwargs
        self.assertEqual(call_kwargs['attempt_number'], 1)
        self.assertEqual(call_kwargs['implementation'], 17)


if __name__ == '__main__':
    unittest.main()
