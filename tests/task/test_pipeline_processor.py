"""
PipelineProcessor 纯逻辑单元测试

测试 _calculate_retry_delay、get_pending_steps、has_steps、apply_results。

只 mock model.database（不 mock model 包），避免跨测试污染。
使用 @patch 装饰器模拟外部依赖。
"""
import importlib
import asyncio
import sys
import unittest
from unittest.mock import MagicMock, patch

# 保存原始模块引用，防止污染后续测试
_saved_model_database = sys.modules.get('model.database')

# 只 mock database 层，不 mock model 包本身
sys.modules['model.database'] = MagicMock()

# 如果 pipeline_processor 已被加载（可能被其他测试用不同 mock 加载过），reload
for _mod in [
    'model.ai_tool_pipeline_steps', 'model.ai_tools', 'model.async_tasks',
    'model.runninghub_slots',
    'task.pipeline_drivers.base_pipeline_driver',
    'task.pipeline_drivers.face_mask_driver',
    'task.pipeline_drivers.image_face_mask_driver',
    'task.pipeline_drivers.implementation_retry_driver',
    'task.pipeline_drivers',
    'task.pipeline_processor',
]:
    if _mod in sys.modules:
        importlib.reload(sys.modules[_mod])

from task.pipeline_processor import PipelineProcessor
import task.pipeline_processor as _pp

# 恢复 model.database，防止污染后续测试
if _saved_model_database is not None:
    sys.modules['model.database'] = _saved_model_database
else:
    sys.modules.pop('model.database', None)


class TestCalculateRetryDelay(unittest.TestCase):
    """测试 PipelineProcessor._calculate_retry_delay() 的指数退避逻辑"""

    def test_retry_count_0_returns_30(self):
        """第 0 次重试返回 30 秒"""
        self.assertEqual(PipelineProcessor._calculate_retry_delay(0), 30)

    def test_retry_count_1_returns_60(self):
        """第 1 次重试返回 60 秒"""
        self.assertEqual(PipelineProcessor._calculate_retry_delay(1), 60)

    def test_retry_count_2_returns_120(self):
        """第 2 次重试返回 120 秒"""
        self.assertEqual(PipelineProcessor._calculate_retry_delay(2), 120)

    def test_retry_count_3_returns_300(self):
        """第 3 次重试返回 300 秒"""
        self.assertEqual(PipelineProcessor._calculate_retry_delay(3), 300)

    def test_retry_count_4_returns_300(self):
        """第 4 次重试返回 300 秒（base_delays 的最后一个值）"""
        self.assertEqual(PipelineProcessor._calculate_retry_delay(4), 300)

    def test_retry_count_exceeds_returns_300(self):
        """超过 base_delays 长度时返回默认值 300 秒"""
        self.assertEqual(PipelineProcessor._calculate_retry_delay(10), 300)

    def test_retry_count_negative_returns_300(self):
        """负数索引访问 base_delays[-1]，Python 返回最后一个元素 300"""
        self.assertEqual(PipelineProcessor._calculate_retry_delay(-1), 300)


class TestPipelineProcessorGetPendingSteps(unittest.TestCase):
    """测试 PipelineProcessor.get_pending_steps() 委托调用"""

    @patch('task.pipeline_processor.PipelineStepModel')
    def test_delegates_to_model(self, MockStepModel):
        """get_pending_steps 正确委托给 PipelineStepModel.get_pending_steps"""
        MockStepModel.get_pending_steps.return_value = ['step1', 'step2']

        result = PipelineProcessor.get_pending_steps(ai_tool_id=1, stage='param_prepare')

        MockStepModel.get_pending_steps.assert_called_once_with(1, 'param_prepare')
        self.assertEqual(result, ['step1', 'step2'])


class TestPipelineProcessorWaitingSteps(unittest.TestCase):
    @patch('task.pipeline_processor.PipelineProcessor.dispatch_step')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_storyboard_grid_split_step_is_owned_by_grid_task_scheduler(self, MockStepModel, mock_dispatch):
        """storyboard_first_frame_grid_split 不能被全局 before_finish 调度器提前执行。"""
        from model import PipelineStage, PipelineStepType

        step = MagicMock()
        step.id = 52
        step.ai_tool_id = 1075
        step.stage = PipelineStage.BEFORE_FINISH
        step.step_type = PipelineStepType.STORYBOARD_FIRST_FRAME_GRID_SPLIT

        MockStepModel.get_all_waiting_steps.return_value = [step]
        MockStepModel.get_processing_steps.return_value = []
        MockStepModel.get_ready_to_retry_steps.return_value = []

        asyncio.run(PipelineProcessor.process_all_pending_steps())

        mock_dispatch.assert_not_called()
        MockStepModel.update_status.assert_not_called()

    @patch('task.pipeline_processor.PipelineProcessor.dispatch_step')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_completed_retry_does_not_skip_new_pending_retry(self, MockStepModel, mock_dispatch):
        """B 的历史完成记录不能把 B 真实失败后创建的 C 跳过。"""
        from model import PipelineStage, PipelineStepStatus, PipelineStepType

        completed_b = MagicMock(
            id=201,
            stage=PipelineStage.BEFORE_FINISH,
            step_type=PipelineStepType.IMPLEMENTATION_RETRY,
            status=PipelineStepStatus.COMPLETED,
        )
        pending_c = MagicMock(
            id=202,
            stage=PipelineStage.BEFORE_FINISH,
            step_type=PipelineStepType.IMPLEMENTATION_RETRY,
            status=PipelineStepStatus.PENDING,
        )
        pending_c.get_params_dict.return_value = {
            'retry_mode': 'single_candidate_v1',
            'target_implementation': 'impl_c',
        }
        MockStepModel.get_by_ai_tool_and_stage.return_value = [completed_b, pending_c]

        asyncio.run(PipelineProcessor._check_ai_tool_stage_completion(10, PipelineStage.BEFORE_FINISH))

        MockStepModel.update_status.assert_not_called()
        mock_dispatch.assert_not_called()

    @patch('task.pipeline_processor.PipelineStepModel')
    def test_completed_and_processing_retry_waits_without_recursion(self, MockStepModel):
        """COMPLETED + PROCESSING 只等待，不发生无状态变化递归。"""
        from model import PipelineStage, PipelineStepStatus, PipelineStepType

        completed = MagicMock(
            id=211,
            stage=PipelineStage.BEFORE_FINISH,
            step_type=PipelineStepType.IMPLEMENTATION_RETRY,
            status=PipelineStepStatus.COMPLETED,
        )
        processing = MagicMock(
            id=212,
            stage=PipelineStage.BEFORE_FINISH,
            step_type=PipelineStepType.IMPLEMENTATION_RETRY,
            status=PipelineStepStatus.PROCESSING,
        )
        MockStepModel.get_by_ai_tool_and_stage.return_value = [completed, processing]

        asyncio.run(PipelineProcessor._check_ai_tool_stage_completion(10, PipelineStage.BEFORE_FINISH))

        MockStepModel.update_status.assert_not_called()

    @patch('task.pipeline_processor.PipelineProcessor.dispatch_step')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_legacy_multiple_candidates_keep_first_and_skip_remaining(
        self, MockStepModel, mock_dispatch
    ):
        """升级前多个候选只执行第一个，其余旧式候选做兼容性跳过。"""
        from model import PipelineStage, PipelineStepStatus, PipelineStepType

        legacy_b = MagicMock(
            id=221, ai_tool_id=10, stage=PipelineStage.BEFORE_FINISH,
            step_type=PipelineStepType.IMPLEMENTATION_RETRY,
        )
        legacy_b.get_params_dict.return_value = {'target_implementation': 'impl_b'}
        legacy_c = MagicMock(
            id=222, ai_tool_id=10, stage=PipelineStage.BEFORE_FINISH,
            step_type=PipelineStepType.IMPLEMENTATION_RETRY,
            status=PipelineStepStatus.PENDING,
        )
        legacy_c.get_params_dict.return_value = {'target_implementation': 'impl_c'}
        legacy_d = MagicMock(
            id=223, ai_tool_id=10, stage=PipelineStage.BEFORE_FINISH,
            step_type=PipelineStepType.IMPLEMENTATION_RETRY,
            status=PipelineStepStatus.PENDING,
        )
        legacy_d.get_params_dict.return_value = {'target_implementation': 'impl_d'}
        MockStepModel.get_all_waiting_steps.return_value = [legacy_b, legacy_c, legacy_d]
        MockStepModel.get_pending_steps.return_value = [legacy_c, legacy_d]
        MockStepModel.get_processing_steps.return_value = []
        MockStepModel.get_ready_to_retry_steps.return_value = []
        mock_dispatch.return_value = True

        asyncio.run(PipelineProcessor.process_all_pending_steps())

        mock_dispatch.assert_called_once_with(legacy_b)
        assert MockStepModel.update_status.call_count == 2
        for call in MockStepModel.update_status.call_args_list:
            assert call.kwargs['result_data']['reason'] == 'legacy_multiple_candidates'

    @patch('task.pipeline_processor.PipelineProcessor.dispatch_step')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_stage_completion_does_not_dispatch_storyboard_grid_split_step(self, MockStepModel, mock_dispatch):
        """implementation_retry 完成后，阶段推进也不能提前派发分镜宫格拆图。"""
        from model import PipelineStage, PipelineStepStatus, PipelineStepType

        retry_step = MagicMock()
        retry_step.id = 119
        retry_step.ai_tool_id = 1120
        retry_step.stage = PipelineStage.BEFORE_FINISH
        retry_step.step_type = PipelineStepType.IMPLEMENTATION_RETRY
        retry_step.status = PipelineStepStatus.COMPLETED

        split_step = MagicMock()
        split_step.id = 118
        split_step.ai_tool_id = 1120
        split_step.stage = PipelineStage.BEFORE_FINISH
        split_step.step_type = PipelineStepType.STORYBOARD_FIRST_FRAME_GRID_SPLIT
        split_step.status = PipelineStepStatus.PENDING

        MockStepModel.get_by_ai_tool_and_stage.return_value = [retry_step, split_step]

        asyncio.run(PipelineProcessor._check_ai_tool_stage_completion(1120, PipelineStage.BEFORE_FINISH))

        mock_dispatch.assert_not_called()


class TestPipelineProcessorHasSteps(unittest.TestCase):
    """测试 PipelineProcessor.has_steps() 委托调用"""

    @patch('task.pipeline_processor.PipelineStepModel')
    def test_delegates_to_model(self, MockStepModel):
        """has_steps 正确委托给 PipelineStepModel.has_steps"""
        MockStepModel.has_steps.return_value = True

        result = PipelineProcessor.has_steps(ai_tool_id=5, stage='before_finish')

        MockStepModel.has_steps.assert_called_once_with(5, 'before_finish')
        self.assertTrue(result)


class TestPipelineProcessorApplyResults(unittest.TestCase):
    """测试 PipelineProcessor.apply_results() 步骤结果应用"""

    def _make_ai_tool(self, ai_tool_id=1):
        ai_tool = MagicMock()
        ai_tool.id = ai_tool_id
        return ai_tool

    def _make_step(self, status, step_type, result_url=None):
        step = MagicMock()
        step.status = status
        step.step_type = step_type
        step.result_url = result_url
        step.get_params_dict.return_value = {}
        return step

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_face_mask_result_applies_video_path(self, MockStepModel, MockAITools):
        """已完成的 face_mask 步骤将 result_url 写入 ai_tool.video_path"""
        ai_tool = self._make_ai_tool(ai_tool_id=10)
        # 使用真实的 COMPLETED 常量值
        from model import PipelineStepStatus
        completed_step = self._make_step(
            status=PipelineStepStatus.COMPLETED,
            step_type='face_mask',
            result_url='/path/to/masked_video.mp4'
        )
        MockStepModel.get_by_ai_tool_and_stage.return_value = [completed_step]

        PipelineProcessor.apply_results(ai_tool, 'param_prepare')

        MockAITools.update.assert_called_once_with(
            10, video_path='/path/to/masked_video.mp4'
        )

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_h3_prompt_optimize_applies_prompt_and_keeps_original(self, MockStepModel, MockAITools):
        from model import PipelineStepStatus, PipelineStepType
        ai_tool = self._make_ai_tool(ai_tool_id=34)
        ai_tool.prompt = 'old prompt'
        ai_tool.extra_config = '{"resolution": "720P"}'
        step = self._make_step(
            status=PipelineStepStatus.COMPLETED,
            step_type=PipelineStepType.H3_PROMPT_OPTIMIZE,
        )
        step.get_result_data_dict.return_value = {
            'original_prompt': 'old prompt',
            'optimized_prompt': 'optimized english prompt',
            'variant': 'I2VA',
            'fallback': False,
        }
        MockStepModel.get_by_ai_tool_and_stage.return_value = [step]

        PipelineProcessor.apply_results(ai_tool, 'param_prepare')

        kwargs = MockAITools.update.call_args.kwargs or {}
        if not kwargs:
            args, kwargs = MockAITools.update.call_args
            # update(id, prompt=..., extra_config=...)
        self.assertEqual(MockAITools.update.call_args[0][0], 34)
        called_kwargs = MockAITools.update.call_args[1]
        self.assertEqual(called_kwargs['prompt'], 'optimized english prompt')
        self.assertIn('old prompt', called_kwargs['extra_config'])
        self.assertIn('optimized english prompt', called_kwargs['extra_config'])

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_no_completed_steps_skips(self, MockStepModel, MockAITools):
        """没有已完成的步骤时，不调用 AIToolsModel.update"""
        ai_tool = self._make_ai_tool(ai_tool_id=10)
        from model import PipelineStepStatus
        pending_step = self._make_step(
            status=PipelineStepStatus.PENDING,
            step_type='face_mask',
            result_url='/path/to/video.mp4'
        )
        MockStepModel.get_by_ai_tool_and_stage.return_value = [pending_step]

        PipelineProcessor.apply_results(ai_tool, 'param_prepare')

        MockAITools.update.assert_not_called()

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_non_face_mask_step_ignored(self, MockStepModel, MockAITools):
        """已完成的非 face_mask 类型步骤不触发 AIToolsModel.update"""
        ai_tool = self._make_ai_tool(ai_tool_id=10)
        from model import PipelineStepStatus
        completed_step = self._make_step(
            status=PipelineStepStatus.COMPLETED,
            step_type='implementation_retry',
            result_url=None
        )
        MockStepModel.get_by_ai_tool_and_stage.return_value = [completed_step]

        PipelineProcessor.apply_results(ai_tool, 'param_prepare')

        MockAITools.update.assert_not_called()

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_face_mask_without_result_url_skips(self, MockStepModel, MockAITools):
        """已完成的 face_mask 步骤但 result_url 为 None 时不更新"""
        ai_tool = self._make_ai_tool(ai_tool_id=10)
        from model import PipelineStepStatus
        completed_step = self._make_step(
            status=PipelineStepStatus.COMPLETED,
            step_type='face_mask',
            result_url=None
        )
        MockStepModel.get_by_ai_tool_and_stage.return_value = [completed_step]

        PipelineProcessor.apply_results(ai_tool, 'param_prepare')

        MockAITools.update.assert_not_called()

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_non_param_prepare_stage_skips(self, MockStepModel, MockAITools):
        """非 param_prepare 阶段不执行结果应用逻辑"""
        ai_tool = self._make_ai_tool(ai_tool_id=10)
        MockStepModel.get_by_ai_tool_and_stage.return_value = []

        PipelineProcessor.apply_results(ai_tool, 'before_finish')

        MockAITools.update.assert_not_called()

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_multiple_steps_only_face_mask_applied(self, MockStepModel, MockAITools):
        """多个步骤中只有已完成的 face_mask 步骤被应用"""
        ai_tool = self._make_ai_tool(ai_tool_id=10)
        from model import PipelineStepStatus
        step1 = self._make_step(
            status=PipelineStepStatus.COMPLETED,
            step_type='face_mask',
            result_url='/path/to/masked.mp4'
        )
        step2 = self._make_step(
            status=PipelineStepStatus.COMPLETED,
            step_type='implementation_retry',
            result_url=None
        )
        step3 = self._make_step(
            status=PipelineStepStatus.PENDING,
            step_type='face_mask',
            result_url=None
        )
        MockStepModel.get_by_ai_tool_and_stage.return_value = [step1, step2, step3]

        PipelineProcessor.apply_results(ai_tool, 'param_prepare')

        MockAITools.update.assert_called_once_with(
            10, video_path='/path/to/masked.mp4'
        )

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_image_face_mask_applies_image_path_by_index(self, MockStepModel, MockAITools):
        """已完成的 image_face_mask 步骤按 index 替换 image_path 中的图片"""
        ai_tool = self._make_ai_tool(ai_tool_id=10)
        ai_tool.image_path = 'first.png,last.png'
        ai_tool.reference_images = None
        from model import PipelineStepStatus
        completed_step = self._make_step(
            status=PipelineStepStatus.COMPLETED,
            step_type='image_face_mask',
            result_url='/upload/cache/masked_first.png'
        )
        completed_step.get_params_dict.return_value = {'field': 'image_path', 'index': 0}
        MockStepModel.get_by_ai_tool_and_stage.return_value = [completed_step]

        PipelineProcessor.apply_results(ai_tool, 'param_prepare')

        MockAITools.update.assert_called_once_with(
            10, image_path='/upload/cache/masked_first.png,last.png'
        )

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_image_face_mask_applies_reference_images_by_index(self, MockStepModel, MockAITools):
        """已完成的 image_face_mask 步骤按 index 替换 reference_images JSON 数组"""
        ai_tool = self._make_ai_tool(ai_tool_id=10)
        ai_tool.image_path = None
        ai_tool.reference_images = '["ref1.png", "ref2.png"]'
        from model import PipelineStepStatus
        completed_step = self._make_step(
            status=PipelineStepStatus.COMPLETED,
            step_type='image_face_mask',
            result_url='/upload/cache/masked_ref2.png'
        )
        completed_step.get_params_dict.return_value = {'field': 'reference_images', 'index': 1}
        MockStepModel.get_by_ai_tool_and_stage.return_value = [completed_step]

        PipelineProcessor.apply_results(ai_tool, 'param_prepare')

        MockAITools.update.assert_called_once_with(
            10, reference_images='["ref1.png", "/upload/cache/masked_ref2.png"]'
        )


class TestNeedsH3AtomicParamPrepare(unittest.TestCase):
    """测试 PipelineProcessor.needs_h3_atomic_param_prepare() 判定"""

    @patch('task.pipeline_drivers.get_dynamic_config_value', return_value=True)
    def test_returns_true_for_h3_type_when_enabled(self, mock_cfg):
        from config.unified_config import TaskTypeId
        self.assertTrue(PipelineProcessor.needs_h3_atomic_param_prepare(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO))

    @patch('task.pipeline_drivers.get_dynamic_config_value', return_value=False)
    def test_returns_false_for_h3_type_when_disabled(self, mock_cfg):
        from config.unified_config import TaskTypeId
        self.assertFalse(PipelineProcessor.needs_h3_atomic_param_prepare(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO))

    @patch('task.pipeline_drivers.get_dynamic_config_value', return_value=True)
    def test_returns_false_for_non_h3_type(self, mock_cfg):
        # 非注册的任务类型 → is_h3_image_to_video_type 返回 False
        self.assertFalse(PipelineProcessor.needs_h3_atomic_param_prepare(99999))


if __name__ == '__main__':
    unittest.main()
