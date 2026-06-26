"""
Pipeline 驱动工厂及驱动实现单元测试

测试 PipelineDriverFactory.create_driver()、FaceMaskPipelineDriver.execute()、
ImplementationRetryPipelineDriver.execute()。

只 mock model.database（不 mock model 包），避免跨测试污染。
使用 @patch 装饰器模拟 execute() 中的外部依赖。
"""
import asyncio
import importlib
import sys
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

# 保存原始模块引用，防止污染后续测试
_saved_modules = {
    'model.database': sys.modules.get('model.database'),
    'api.clients.runninghub_client': sys.modules.get('api.clients.runninghub_client'),
    'config.config_util': sys.modules.get('config.config_util'),
    'utils.file_storage': sys.modules.get('utils.file_storage'),
}

# 只 mock database 层，不 mock model 包本身
sys.modules['model.database'] = MagicMock()

# Mock 需要外部连接的依赖（不影响 model 和 utils.logger_config）
sys.modules['api.clients.runninghub_client'] = MagicMock()
sys.modules['config.config_util'] = MagicMock()
sys.modules['utils.file_storage'] = MagicMock()

# 如果模块已被加载（可能被其他测试用不同 mock 加载过），reload 以使用当前 mock
_reloaded_modules = [
    'model.ai_tool_pipeline_steps', 'model.ai_tools', 'model.runninghub_slots',
    'task.pipeline_drivers.base_pipeline_driver',
    'task.pipeline_drivers.face_mask_driver',
    'task.pipeline_drivers.image_face_mask_driver',
    'task.pipeline_drivers.implementation_retry_driver',
    'task.pipeline_drivers',
]
for _mod in _reloaded_modules:
    if _mod in sys.modules:
        importlib.reload(sys.modules[_mod])

from task.pipeline_drivers import PipelineDriverFactory
from task.pipeline_drivers.face_mask_driver import FaceMaskPipelineDriver
from task.pipeline_drivers.image_face_mask_driver import ImageFaceMaskPipelineDriver
from task.pipeline_drivers.implementation_retry_driver import ImplementationRetryPipelineDriver

# 恢复所有被 mock 的 sys.modules 条目，防止污染后续测试
for _key, _orig in _saved_modules.items():
    if _orig is not None:
        sys.modules[_key] = _orig
    else:
        sys.modules.pop(_key, None)

# 注意：不再从 sys.modules 中移除 reload 过的模块。
# 如果移除，@patch 装饰器会重新导入并创建新的模块对象，
# 但测试代码引用的是旧模块对象中的类，导致 patch 无法生效。
# 保留这些模块以确保 @patch 能正确 patch 到代码实际使用的模块。


class TestPipelineDriverFactoryCreateDriver(unittest.TestCase):
    """测试 PipelineDriverFactory.create_driver 方法"""

    def test_face_mask_returns_driver(self):
        """face_mask 类型应返回 FaceMaskPipelineDriver 实例"""
        driver = PipelineDriverFactory.create_driver('face_mask')
        self.assertIsNotNone(driver)
        self.assertEqual(driver.__class__.__name__, FaceMaskPipelineDriver.__name__)

    def test_implementation_retry_returns_driver(self):
        """implementation_retry 类型应返回 ImplementationRetryPipelineDriver 实例"""
        driver = PipelineDriverFactory.create_driver('implementation_retry')
        self.assertIsNotNone(driver)
        self.assertEqual(driver.__class__.__name__, ImplementationRetryPipelineDriver.__name__)

    def test_image_face_mask_returns_driver(self):
        """image_face_mask 类型应返回 ImageFaceMaskPipelineDriver 实例"""
        driver = PipelineDriverFactory.create_driver('image_face_mask')
        self.assertIsNotNone(driver)
        self.assertEqual(driver.__class__.__name__, ImageFaceMaskPipelineDriver.__name__)

    def test_unknown_type_returns_none(self):
        """未知类型应返回 None"""
        driver = PipelineDriverFactory.create_driver('unknown_type')
        self.assertIsNone(driver)


class TestFaceMaskPipelineDriverExecute(unittest.TestCase):
    """测试 FaceMaskPipelineDriver.execute 方法"""

    def setUp(self):
        self.driver = FaceMaskPipelineDriver()
        self.step = MagicMock()
        self.ai_tool = MagicMock()
        self.ai_tool.user_id = 42

    def test_missing_video_path_returns_error(self):
        """缺少 video_path 参数时返回失败"""
        self.step.get_params_dict.return_value = {}

        result = asyncio.run(self.driver.execute(self.step, self.ai_tool))

        self.assertFalse(result['success'])
        self.assertIn('缺少 video_path', result['error'])

    def test_none_video_path_returns_error(self):
        """video_path 为 None 时返回失败"""
        self.step.get_params_dict.return_value = {'video_path': None}

        result = asyncio.run(self.driver.execute(self.step, self.ai_tool))

        self.assertFalse(result['success'])
        self.assertIn('缺少 video_path', result['error'])

    @patch('task.async_drivers.runninghub_face_mask_driver.RunningHubFaceMaskDriver')
    def test_submit_success_returns_async_task_id(self, MockDriverClass):
        """提交成功时返回 async_task_id"""
        self.step.get_params_dict.return_value = {'video_path': '/tmp/test.mp4'}
        self.step.id = 100

        mock_driver = MagicMock()
        mock_driver.submit_with_slot_management = AsyncMock(return_value={
            'success': True,
            'async_task_id': 200,
            'project_id': 'rh-task-123',
        })
        MockDriverClass.return_value = mock_driver

        result = asyncio.run(self.driver.execute(self.step, self.ai_tool))

        self.assertTrue(result['success'])
        self.assertEqual(result['async_task_id'], 200)

    @patch('task.async_drivers.runninghub_face_mask_driver.RunningHubFaceMaskDriver')
    def test_slot_full_passes_through_error(self, MockDriverClass):
        """槽位满时透传 SLOT_FULL 错误"""
        self.step.get_params_dict.return_value = {'video_path': '/tmp/test.mp4'}
        self.step.id = 100

        mock_driver = MagicMock()
        mock_driver.submit_with_slot_management = AsyncMock(return_value={
            'success': False,
            'error': '槽位已满',
            'error_type': 'SLOT_FULL',
            'async_task_id': 201,
            'retry': True,
        })
        MockDriverClass.return_value = mock_driver

        result = asyncio.run(self.driver.execute(self.step, self.ai_tool))

        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'SLOT_FULL')
        self.assertTrue(result['retry'])

    @patch('task.async_drivers.runninghub_face_mask_driver.RunningHubFaceMaskDriver')
    def test_exception_returns_error(self, MockDriverClass):
        """提交异常时返回错误信息"""
        self.step.get_params_dict.return_value = {'video_path': '/tmp/test.mp4'}
        self.step.id = 100

        mock_driver = MagicMock()
        mock_driver.submit_with_slot_management = AsyncMock(
            side_effect=RuntimeError("unexpected crash")
        )
        MockDriverClass.return_value = mock_driver

        result = asyncio.run(self.driver.execute(self.step, self.ai_tool))

        self.assertFalse(result['success'])
        self.assertIn('提交人脸遮盖任务异常', result['error'])


class TestImplementationRetryPipelineDriverExecute(unittest.TestCase):
    """测试 ImplementationRetryPipelineDriver.execute 方法"""

    def setUp(self):
        self.driver = ImplementationRetryPipelineDriver()
        self.step = MagicMock()
        self.ai_tool = MagicMock()
        self.ai_tool.id = 50
        self.ai_tool.implementation = 1

    def test_missing_target_implementation_returns_error(self):
        """缺少 target_implementation 参数时返回失败"""
        self.step.get_params_dict.return_value = {}

        result = asyncio.run(self.driver.execute(self.step, self.ai_tool))

        self.assertFalse(result['success'])
        self.assertIn('缺少 target_implementation', result['error'])

    @patch('task.pipeline_drivers.implementation_retry_driver.get_implementation_id', return_value=0)
    def test_unknown_implementation_returns_error(self, mock_get_id):
        """未知的实现方名称（返回 0）时返回失败"""
        self.step.get_params_dict.return_value = {'target_implementation': 'unknown_impl'}

        result = asyncio.run(self.driver.execute(self.step, self.ai_tool))

        self.assertFalse(result['success'])
        self.assertIn('未知的实现方', result['error'])

    @patch('task.pipeline_drivers.implementation_retry_driver.get_implementation_id', return_value=2)
    @patch('task.pipeline_drivers.implementation_retry_driver.TasksModel')
    @patch('task.pipeline_drivers.implementation_retry_driver.AIToolsModel')
    def test_success_updates_ai_tool(self, MockAIToolsModel, MockTasksModel, mock_get_id):
        """成功时更新 ai_tools 并返回成功结果"""
        self.step.get_params_dict.return_value = {'target_implementation': 'kling_duomi_v1'}

        result = asyncio.run(self.driver.execute(self.step, self.ai_tool))

        self.assertTrue(result['success'])
        self.assertIn('result_data', result)
        self.assertEqual(result['result_data']['new_implementation_name'], 'kling_duomi_v1')
        MockAIToolsModel.update.assert_called_once()
        MockTasksModel.update_by_task_id.assert_called_once()

    @patch('task.pipeline_drivers.implementation_retry_driver.get_implementation_id', return_value=2)
    @patch('task.pipeline_drivers.implementation_retry_driver.TasksModel')
    @patch('task.pipeline_drivers.implementation_retry_driver.AIToolsModel')
    def test_success_result_data_contains_old_and_new(self, MockAIToolsModel, MockTasksModel, mock_get_id):
        """成功返回的 result_data 应包含新旧实现方信息"""
        self.ai_tool.implementation = 1
        self.step.get_params_dict.return_value = {'target_implementation': 'kling_duomi_v1'}

        result = asyncio.run(self.driver.execute(self.step, self.ai_tool))

        self.assertTrue(result['success'])
        self.assertEqual(result['result_data']['old_implementation'], 1)
        self.assertEqual(result['result_data']['new_implementation'], 2)

    def test_exception_returns_error(self):
        """异常时返回失败"""
        self.step.get_params_dict = MagicMock(side_effect=RuntimeError("db error"))

        result = asyncio.run(self.driver.execute(self.step, self.ai_tool))

        self.assertFalse(result['success'])
        self.assertIn('实现方重试异常', result['error'])


if __name__ == '__main__':
    unittest.main()


# ==================== 新增：PipelineDriverFactory.create_param_prepare_steps 测试 ====================

class TestCreateParamPrepareSteps(unittest.TestCase):
    """测试 PipelineDriverFactory.create_param_prepare_steps()"""

    @patch('task.pipeline_drivers.AIToolsModel')
    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_unknown_task_type_returns_empty(self, MockRegistry, MockAITools):
        """未知任务类型返回空列表"""
        MockRegistry.get_by_id.return_value = None

        result = PipelineDriverFactory.create_param_prepare_steps(ai_tool_id=1, ai_tool_type=999)
        self.assertEqual(result, [])

    @patch('task.pipeline_drivers.AIToolsModel')
    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_no_rule_for_key_returns_empty(self, MockRegistry, MockAITools):
        """没有匹配的规则返回空列表"""
        mock_config = MagicMock()
        mock_config.key = 'some_unknown_key'
        MockRegistry.get_by_id.return_value = mock_config

        result = PipelineDriverFactory.create_param_prepare_steps(ai_tool_id=1, ai_tool_type=1)
        self.assertEqual(result, [])

    @patch('task.pipeline_drivers.AIToolsModel')
    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_ai_tool_not_found_returns_empty(self, MockRegistry, MockAITools):
        """ai_tool 不存在返回空列表"""
        mock_config = MagicMock()
        mock_config.key = 'seedance_2_0_image_to_video'
        MockRegistry.get_by_id.return_value = mock_config
        MockAITools.get_by_id.return_value = None

        result = PipelineDriverFactory.create_param_prepare_steps(ai_tool_id=999, ai_tool_type=1)
        self.assertEqual(result, [])

    @patch('task.pipeline_drivers.get_dynamic_config_value')
    @patch('task.pipeline_drivers.PipelineStepModel')
    @patch('task.pipeline_drivers.AIToolsModel')
    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_seedance_image_path_creates_image_face_mask_steps(
        self, MockRegistry, MockAITools, MockStepModel, mock_config
    ):
        """Seedance 2.0 的 image_path 首尾帧应创建 image_face_mask 步骤"""
        mock_task_config = MagicMock()
        mock_task_config.key = 'seedance_2_0_image_to_video'
        MockRegistry.get_by_id.return_value = mock_task_config
        mock_ai_tool = MagicMock()
        mock_ai_tool.image_path = 'first.png,last.png'
        mock_ai_tool.reference_images = None
        mock_ai_tool.video_path = None
        MockAITools.get_by_id.return_value = mock_ai_tool
        mock_config.side_effect = (
            lambda section, key, default=None:
            True if (section, key) == ('pipeline', 'seedance_face_mask_enabled') else default
        )
        MockStepModel.create.side_effect = [101, 102]

        result = PipelineDriverFactory.create_param_prepare_steps(ai_tool_id=9, ai_tool_type=23)

        self.assertEqual(result, [101, 102])
        self.assertEqual(MockStepModel.create.call_count, 2)
        first_call = MockStepModel.create.call_args_list[0].kwargs
        second_call = MockStepModel.create.call_args_list[1].kwargs
        self.assertEqual(first_call['step_type'], 'image_face_mask')
        self.assertEqual(first_call['params']['image_path'], 'first.png')
        self.assertEqual(first_call['params']['field'], 'image_path')
        self.assertEqual(first_call['params']['index'], 0)
        self.assertEqual(first_call['target'], 'first.png')
        self.assertEqual(second_call['params']['image_path'], 'last.png')
        self.assertEqual(second_call['params']['index'], 1)

    @patch('task.pipeline_drivers.get_dynamic_config_value')
    @patch('task.pipeline_drivers.PipelineStepModel')
    @patch('task.pipeline_drivers.AIToolsModel')
    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_seedance_reference_images_creates_image_face_mask_steps(
        self, MockRegistry, MockAITools, MockStepModel, mock_config
    ):
        """Seedance 2.0 Fast 的 reference_images 应创建 image_face_mask 步骤"""
        mock_task_config = MagicMock()
        mock_task_config.key = 'seedance_2_0_fast_image_to_video'
        MockRegistry.get_by_id.return_value = mock_task_config
        mock_ai_tool = MagicMock()
        mock_ai_tool.image_path = None
        mock_ai_tool.reference_images = '["ref1.png", "ref2.png"]'
        mock_ai_tool.video_path = None
        MockAITools.get_by_id.return_value = mock_ai_tool
        mock_config.side_effect = (
            lambda section, key, default=None:
            True if (section, key) == ('pipeline', 'seedance_face_mask_enabled') else default
        )
        MockStepModel.create.side_effect = [201, 202]

        result = PipelineDriverFactory.create_param_prepare_steps(ai_tool_id=10, ai_tool_type=22)

        self.assertEqual(result, [201, 202])
        first_call = MockStepModel.create.call_args_list[0].kwargs
        self.assertEqual(first_call['step_type'], 'image_face_mask')
        self.assertEqual(first_call['params']['field'], 'reference_images')
        self.assertEqual(first_call['params']['index'], 0)
        self.assertEqual(first_call['target'], 'ref1.png')

    @patch('task.pipeline_drivers.get_dynamic_config_value')
    @patch('task.pipeline_drivers.PipelineStepModel')
    @patch('task.pipeline_drivers.AIToolsModel')
    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_seedance_image_face_mask_switch_off_skips_image_steps(
        self, MockRegistry, MockAITools, MockStepModel, mock_config
    ):
        """图片前置处理开关关闭时不创建 image_face_mask 步骤"""
        mock_task_config = MagicMock()
        mock_task_config.key = 'seedance_2_0_image_to_video'
        MockRegistry.get_by_id.return_value = mock_task_config
        mock_ai_tool = MagicMock()
        mock_ai_tool.image_path = 'first.png'
        mock_ai_tool.reference_images = None
        mock_ai_tool.video_path = None
        MockAITools.get_by_id.return_value = mock_ai_tool
        mock_config.side_effect = (
            lambda section, key, default=None:
            False if (section, key) == ('pipeline', 'seedance_face_mask_enabled') else default
        )

        result = PipelineDriverFactory.create_param_prepare_steps(ai_tool_id=9, ai_tool_type=23)

        self.assertEqual(result, [])
        MockStepModel.create.assert_not_called()

    @patch('task.pipeline_drivers.get_dynamic_config_value')
    @patch('task.pipeline_drivers.PipelineStepModel')
    @patch('task.pipeline_drivers.AIToolsModel')
    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_seedance_face_mask_switch_off_skips_video_steps(
        self, MockRegistry, MockAITools, MockStepModel, mock_config
    ):
        """人脸遮罩总开关关闭时，视频输入也不创建 face_mask 步骤"""
        mock_task_config = MagicMock()
        mock_task_config.key = 'seedance_2_0_image_to_video'
        MockRegistry.get_by_id.return_value = mock_task_config
        mock_ai_tool = MagicMock()
        mock_ai_tool.image_path = None
        mock_ai_tool.reference_images = None
        mock_ai_tool.video_path = 'input.mp4'
        MockAITools.get_by_id.return_value = mock_ai_tool
        mock_config.side_effect = (
            lambda section, key, default=None:
            False if (section, key) == ('pipeline', 'seedance_face_mask_enabled') else default
        )

        result = PipelineDriverFactory.create_param_prepare_steps(ai_tool_id=11, ai_tool_type=23)

        self.assertEqual(result, [])
        MockStepModel.create.assert_not_called()


# ==================== 新增：PipelineDriverFactory.create_before_finish_steps 测试 ====================

class TestCreateBeforeFinishSteps(unittest.TestCase):
    """测试 PipelineDriverFactory.create_before_finish_steps()"""

    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_no_task_config_returns_empty(self, MockRegistry):
        """无任务配置返回空列表"""
        MockRegistry.get_by_id.return_value = None

        result = PipelineDriverFactory.create_before_finish_steps(
            ai_tool_id=1, ai_tool_type=999,
            failed_implementation=1, failure_reason='timeout'
        )
        self.assertEqual(result, [])

    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_no_implementations_returns_empty(self, MockRegistry):
        """任务配置无实现方返回空列表"""
        mock_config = MagicMock()
        mock_config.implementations = None
        MockRegistry.get_by_id.return_value = mock_config

        result = PipelineDriverFactory.create_before_finish_steps(
            ai_tool_id=1, ai_tool_type=1,
            failed_implementation=1, failure_reason='error'
        )
        self.assertEqual(result, [])

    @patch('model.implementation_attempts.ImplementationAttemptModel')
    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_no_alternatives_returns_empty(self, MockRegistry, MockAttemptModel):
        """无可用替代实现方返回空列表"""
        mock_config = MagicMock()
        mock_config._get_implementations_info.return_value = [
            {'name': 'impl_a', 'sort_order': 100},
            {'name': 'impl_b', 'sort_order': 200},
        ]
        MockRegistry.get_by_id.return_value = mock_config

        # 所有实现方都已尝试过
        MockAttemptModel.get_attempted_implementations.return_value = {1, 2}

        with patch('task.pipeline_drivers.get_implementation_name', return_value='impl_a'):
            result = PipelineDriverFactory.create_before_finish_steps(
                ai_tool_id=1, ai_tool_type=1,
                failed_implementation=1, failure_reason='error'
            )
        self.assertEqual(result, [])

    @patch('model.implementation_attempts.ImplementationAttemptModel')
    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    @patch('task.pipeline_drivers.PipelineStepModel')
    def test_creates_retry_steps_for_alternatives(
        self, MockStepModel, MockRegistry, MockAttemptModel
    ):
        """为可用替代方创建重试步骤"""
        mock_config = MagicMock()
        mock_config._get_implementations_info.return_value = [
            {'name': 'impl_a', 'sort_order': 100},
            {'name': 'impl_b', 'sort_order': 200},
        ]
        MockRegistry.get_by_id.return_value = mock_config

        # 只尝试过 impl_a
        MockAttemptModel.get_attempted_implementations.return_value = {1}

        # impl_b 的驱动可用
        MockRegistry.get_implementation.return_value = MagicMock(is_enabled=MagicMock(return_value=True))
        mock_vdf = MagicMock()
        mock_vdf.create_driver_by_implementation.return_value = MagicMock()

        MockStepModel.create.return_value = 42

        # 通过 sys.modules 注入 mock，避免触发 VideoDriverFactory 真实 import chain
        mock_visual = MagicMock()
        mock_visual.VideoDriverFactory = mock_vdf
        with patch.dict('sys.modules', {'task.visual_drivers': mock_visual}):
            with patch('task.pipeline_drivers.get_implementation_name', side_effect=lambda x: 'impl_a' if x == 1 else 'impl_b'):
                with patch('task.pipeline_drivers.get_implementation_id', return_value=2):
                    result = PipelineDriverFactory.create_before_finish_steps(
                        ai_tool_id=1, ai_tool_type=1,
                        failed_implementation=1, failure_reason='error'
                    )
        # 应创建了至少一个重试步骤
        self.assertGreater(len(result), 0)


# ==================== 新增：PipelineDriverFactory.is_seedance_face_mask_type 测试 ====================

class TestIsSeedanceFaceMaskType(unittest.TestCase):
    """测试 PipelineDriverFactory.is_seedance_face_mask_type()"""

    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_mini_is_seedance_face_mask(self, MockRegistry):
        """Seedance 2.0 Mini (type=31) 应识别为走人脸遮盖的 Seedance 模型"""
        mock_config = MagicMock()
        mock_config.key = 'seedance_2_0_mini_image_to_video'
        MockRegistry.get_by_id.return_value = mock_config

        self.assertTrue(PipelineDriverFactory.is_seedance_face_mask_type(31))

    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_seedance_2_0_and_fast_are_face_mask(self, MockRegistry):
        """Seedance 2.0 (23) 与 2.0 Fast (22) 仍被识别"""
        cases = {23: 'seedance_2_0_image_to_video', 22: 'seedance_2_0_fast_image_to_video'}
        for task_type, key in cases.items():
            mock_config = MagicMock()
            mock_config.key = key
            MockRegistry.get_by_id.return_value = mock_config
            self.assertTrue(
                PipelineDriverFactory.is_seedance_face_mask_type(task_type),
                f"{key} should be seedance face mask type"
            )

    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_non_seedance_is_not_face_mask(self, MockRegistry):
        """非 Seedance 模型（如 Kling）应返回 False"""
        mock_config = MagicMock()
        mock_config.key = 'kling_image_to_video'
        MockRegistry.get_by_id.return_value = mock_config

        self.assertFalse(PipelineDriverFactory.is_seedance_face_mask_type(12))

    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_unknown_task_type_returns_false(self, MockRegistry):
        """未知任务类型返回 False"""
        MockRegistry.get_by_id.return_value = None

        self.assertFalse(PipelineDriverFactory.is_seedance_face_mask_type(999))


# ==================== 新增：Seedance 2.0 Mini 的 param_prepare 步骤创建测试 ====================

class TestCreateParamPrepareStepsMini(unittest.TestCase):
    """测试 Seedance 2.0 Mini 的 param_prepare 步骤创建"""

    @patch('task.pipeline_drivers.get_dynamic_config_value')
    @patch('task.pipeline_drivers.PipelineStepModel')
    @patch('task.pipeline_drivers.AIToolsModel')
    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_mini_image_path_creates_image_face_mask_steps(
        self, MockRegistry, MockAITools, MockStepModel, mock_config
    ):
        """Seedance 2.0 Mini 的 image_path 首尾帧应创建 image_face_mask 步骤"""
        mock_task_config = MagicMock()
        mock_task_config.key = 'seedance_2_0_mini_image_to_video'
        MockRegistry.get_by_id.return_value = mock_task_config
        mock_ai_tool = MagicMock()
        mock_ai_tool.image_path = 'first.png,last.png'
        mock_ai_tool.reference_images = None
        mock_ai_tool.video_path = None
        MockAITools.get_by_id.return_value = mock_ai_tool
        mock_config.side_effect = (
            lambda section, key, default=None:
            True if (section, key) == ('pipeline', 'seedance_face_mask_enabled') else default
        )
        MockStepModel.create.side_effect = [301, 302]

        result = PipelineDriverFactory.create_param_prepare_steps(ai_tool_id=12, ai_tool_type=31)

        self.assertEqual(result, [301, 302])
        self.assertEqual(MockStepModel.create.call_count, 2)
        first_call = MockStepModel.create.call_args_list[0].kwargs
        self.assertEqual(first_call['step_type'], 'image_face_mask')
        self.assertEqual(first_call['params']['image_path'], 'first.png')

    @patch('task.pipeline_drivers.get_dynamic_config_value')
    @patch('task.pipeline_drivers.PipelineStepModel')
    @patch('task.pipeline_drivers.AIToolsModel')
    @patch('task.pipeline_drivers.UnifiedConfigRegistry')
    def test_mini_video_path_creates_face_mask_steps(
        self, MockRegistry, MockAITools, MockStepModel, mock_config
    ):
        """Seedance 2.0 Mini 的 video_path 应创建 face_mask 步骤"""
        mock_task_config = MagicMock()
        mock_task_config.key = 'seedance_2_0_mini_image_to_video'
        MockRegistry.get_by_id.return_value = mock_task_config
        mock_ai_tool = MagicMock()
        mock_ai_tool.image_path = None
        mock_ai_tool.reference_images = None
        mock_ai_tool.video_path = 'input.mp4'
        MockAITools.get_by_id.return_value = mock_ai_tool
        mock_config.side_effect = (
            lambda section, key, default=None:
            True if (section, key) == ('pipeline', 'seedance_face_mask_enabled') else default
        )
        MockStepModel.create.side_effect = [303]

        result = PipelineDriverFactory.create_param_prepare_steps(ai_tool_id=13, ai_tool_type=31)

        self.assertEqual(result, [303])
        first_call = MockStepModel.create.call_args_list[0].kwargs
        self.assertEqual(first_call['step_type'], 'face_mask')
        self.assertEqual(first_call['params']['video_path'], 'input.mp4')
        self.assertEqual(first_call['target'], 'input.mp4')
