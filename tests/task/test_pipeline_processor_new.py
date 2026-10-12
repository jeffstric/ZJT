"""
PipelineProcessor 单元测试

测试 Pipeline 编排器的核心逻辑方法。
"""
import unittest
from unittest.mock import patch, MagicMock


class TestCalculateRetryDelay(unittest.TestCase):
    """测试 PipelineProcessor._calculate_retry_delay()"""

    def test_retry_count_0(self):
        """重试次数 0 返回 30 秒"""
        from task.pipeline_processor import PipelineProcessor
        result = PipelineProcessor._calculate_retry_delay(0)
        self.assertEqual(result, 30)

    def test_retry_count_1(self):
        """重试次数 1 返回 60 秒"""
        from task.pipeline_processor import PipelineProcessor
        result = PipelineProcessor._calculate_retry_delay(1)
        self.assertEqual(result, 60)

    def test_retry_count_2(self):
        """重试次数 2 返回 120 秒"""
        from task.pipeline_processor import PipelineProcessor
        result = PipelineProcessor._calculate_retry_delay(2)
        self.assertEqual(result, 120)

    def test_retry_count_3(self):
        """重试次数 3 返回 300 秒"""
        from task.pipeline_processor import PipelineProcessor
        result = PipelineProcessor._calculate_retry_delay(3)
        self.assertEqual(result, 300)

    def test_retry_count_4(self):
        """重试次数 4 返回 300 秒（最大值）"""
        from task.pipeline_processor import PipelineProcessor
        result = PipelineProcessor._calculate_retry_delay(4)
        self.assertEqual(result, 300)

    def test_retry_count_large(self):
        """重试次数超过数组长度返回 300 秒"""
        from task.pipeline_processor import PipelineProcessor
        result = PipelineProcessor._calculate_retry_delay(10)
        self.assertEqual(result, 300)


class TestCreateParamPrepareSteps(unittest.TestCase):
    """测试 PipelineProcessor.create_param_prepare_steps()"""

    @patch('task.pipeline_processor.PipelineDriverFactory')
    def test_delegates_to_factory(self, mock_factory):
        """委托给 PipelineDriverFactory"""
        from task.pipeline_processor import PipelineProcessor
        mock_factory.create_param_prepare_steps.return_value = [1, 2, 3]

        result = PipelineProcessor.create_param_prepare_steps(100, 'generate_video')

        self.assertEqual(result, [1, 2, 3])
        mock_factory.create_param_prepare_steps.assert_called_once_with(100, 'generate_video')


class TestCreateBeforeFinishSteps(unittest.TestCase):
    """测试 PipelineProcessor.create_before_finish_steps()"""

    @patch('task.pipeline_processor.PipelineDriverFactory')
    def test_delegates_to_factory(self, mock_factory):
        """委托给 PipelineDriverFactory"""
        from task.pipeline_processor import PipelineProcessor
        mock_factory.create_before_finish_steps.return_value = [4, 5]

        result = PipelineProcessor.create_before_finish_steps(100, 'generate_video', 1, 'timeout')

        self.assertEqual(result, [4, 5])
        mock_factory.create_before_finish_steps.assert_called_once_with(
            100, 'generate_video', 1, 'timeout'
        )


class TestGetPendingSteps(unittest.TestCase):
    """测试 PipelineProcessor.get_pending_steps()"""

    @patch('task.pipeline_processor.PipelineStepModel')
    def test_delegates_to_model(self, mock_model):
        """委托给 PipelineStepModel"""
        from task.pipeline_processor import PipelineProcessor
        mock_steps = [MagicMock(), MagicMock()]
        mock_model.get_pending_steps.return_value = mock_steps

        result = PipelineProcessor.get_pending_steps(100, 'param_prepare')

        self.assertEqual(result, mock_steps)
        mock_model.get_pending_steps.assert_called_once_with(100, 'param_prepare')


class TestGetAllSteps(unittest.TestCase):
    """测试 PipelineProcessor.get_all_steps()"""

    @patch('task.pipeline_processor.PipelineStepModel')
    def test_delegates_to_model(self, mock_model):
        """委托给 PipelineStepModel"""
        from task.pipeline_processor import PipelineProcessor
        mock_steps = [MagicMock(), MagicMock()]
        mock_model.get_by_ai_tool_and_stage.return_value = mock_steps

        result = PipelineProcessor.get_all_steps(100, 'param_prepare')

        self.assertEqual(result, mock_steps)
        mock_model.get_by_ai_tool_and_stage.assert_called_once_with(100, 'param_prepare')


class TestHasSteps(unittest.TestCase):
    """测试 PipelineProcessor.has_steps()"""

    @patch('task.pipeline_processor.PipelineStepModel')
    def test_returns_true_when_steps_exist(self, mock_model):
        """存在步骤时返回 True"""
        from task.pipeline_processor import PipelineProcessor
        mock_model.has_steps.return_value = True

        result = PipelineProcessor.has_steps(100, 'param_prepare')

        self.assertTrue(result)

    @patch('task.pipeline_processor.PipelineStepModel')
    def test_returns_false_when_no_steps(self, mock_model):
        """不存在步骤时返回 False"""
        from task.pipeline_processor import PipelineProcessor
        mock_model.has_steps.return_value = False

        result = PipelineProcessor.has_steps(100, 'param_prepare')

        self.assertFalse(result)


class TestApplyResults(unittest.TestCase):
    """测试 PipelineProcessor.apply_results()"""

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_apply_face_mask_result(self, mock_step_model, mock_ai_tools_model):
        """应用 face_mask 步骤结果到 ai_tool"""
        from task.pipeline_processor import PipelineProcessor
        from model.ai_tool_pipeline_steps import PipelineStepStatus

        mock_step = MagicMock()
        mock_step.status = PipelineStepStatus.COMPLETED  # 2
        mock_step.step_type = 'face_mask'
        mock_step.result_url = 'http://example.com/masked_video.mp4'

        mock_step_model.get_by_ai_tool_and_stage.return_value = [mock_step]

        mock_ai_tool = MagicMock()
        mock_ai_tool.id = 100

        PipelineProcessor.apply_results(mock_ai_tool, 'param_prepare')

        mock_ai_tools_model.update.assert_called_once_with(100, video_path='http://example.com/masked_video.mp4')

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_skip_non_completed_steps(self, mock_step_model, mock_ai_tools_model):
        """跳过未完成的步骤"""
        from task.pipeline_processor import PipelineProcessor
        from model.ai_tool_pipeline_steps import PipelineStepStatus

        mock_step = MagicMock()
        mock_step.status = PipelineStepStatus.PENDING  # 0
        mock_step.step_type = 'face_mask'

        mock_step_model.get_by_ai_tool_and_stage.return_value = [mock_step]

        mock_ai_tool = MagicMock()
        mock_ai_tool.id = 100

        PipelineProcessor.apply_results(mock_ai_tool, 'param_prepare')

        mock_ai_tools_model.update.assert_not_called()

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_apply_h3_optimize_keeps_dialogue_flag(self, mock_step_model, mock_ai_tools_model):
        """H3 优化步骤回写必须保留 has_dialogue 标记

        execute 已把 LLM 台词标记写入 extra_config；apply_results 二次 merge
        若不带标记，会把标记抹成 null，KFRef 驱动将永远回退正则判断。
        """
        import json as _json
        from task.pipeline_processor import PipelineProcessor
        from model import PipelineStepType
        from model.ai_tool_pipeline_steps import PipelineStepStatus

        mock_step = MagicMock()
        mock_step.status = PipelineStepStatus.COMPLETED
        mock_step.step_type = PipelineStepType.H3_PROMPT_OPTIMIZE
        mock_step.get_result_data_dict.return_value = {
            "original_prompt": "原文",
            "optimized_prompt": "优化后",
            "variant": "KFRef",
            "fallback": False,
            "has_dialogue": False,
        }
        mock_step_model.get_by_ai_tool_and_stage.return_value = [mock_step]

        mock_ai_tool = MagicMock()
        mock_ai_tool.id = 100
        mock_ai_tool.extra_config = None

        PipelineProcessor.apply_results(mock_ai_tool, 'param_prepare')

        mock_ai_tools_model.update.assert_called_once()
        kwargs = mock_ai_tools_model.update.call_args.kwargs
        extra = _json.loads(kwargs["extra_config"])
        self.assertEqual(extra["h3_prompt_optimize"]["optimized_prompt"], "优化后")
        self.assertIs(extra["h3_prompt_optimize"]["has_dialogue"], False)

    @patch('task.pipeline_processor.AIToolsModel')
    @patch('task.pipeline_processor.PipelineStepModel')
    def test_skip_non_face_mask_steps(self, mock_step_model, mock_ai_tools_model):
        """跳过非 face_mask 步骤"""
        from task.pipeline_processor import PipelineProcessor
        from model.ai_tool_pipeline_steps import PipelineStepStatus

        mock_step = MagicMock()
        mock_step.status = PipelineStepStatus.COMPLETED  # 2
        mock_step.step_type = 'other_type'

        mock_step_model.get_by_ai_tool_and_stage.return_value = [mock_step]

        mock_ai_tool = MagicMock()
        mock_ai_tool.id = 100

        PipelineProcessor.apply_results(mock_ai_tool, 'param_prepare')

        mock_ai_tools_model.update.assert_not_called()


if __name__ == '__main__':
    unittest.main()
