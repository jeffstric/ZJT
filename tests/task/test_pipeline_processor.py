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


if __name__ == '__main__':
    unittest.main()
