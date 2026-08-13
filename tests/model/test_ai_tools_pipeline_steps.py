"""
AIToolsModel.create_with_pipeline_steps 单元测试

验证 Seedance 前置处理步骤在实际 ai_tools 创建入口中的生成行为。
"""
import json
import unittest
from unittest.mock import MagicMock, patch

from model.ai_tools import AIToolsModel
from model.ai_tool_pipeline_steps import PipelineStepType, PipelineStage


class _FakeTransaction:
    def __init__(self):
        self.conn = MagicMock(name="conn")

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        return False


class TestCreateWithPipelineSteps(unittest.TestCase):
    """测试创建 ai_tool 时同步创建前置处理步骤"""

    def _call_create(self, **overrides):
        params = {
            'prompt': 'test prompt',
            'user_id': 1,
            'type': 100,
            'image_path': None,
            'reference_images': None,
            'video_path': None,
        }
        params.update(overrides)
        return AIToolsModel.create_with_pipeline_steps(**params)

    @patch('config.config_util.get_dynamic_config_value')
    @patch('config.constant.Edition.is_community', return_value=False)
    @patch('model.ai_tool_pipeline_steps.PipelineStepModel.create_in_transaction')
    @patch('model.database.execute_insert_in_transaction', return_value=123)
    @patch('model.database.transaction', return_value=_FakeTransaction())
    def test_creates_video_and_image_face_mask_steps(
        self,
        mock_transaction,
        mock_insert,
        mock_create_step,
        mock_is_community,
        mock_config,
    ):
        """视频、首尾帧、参考图都会创建对应前置处理步骤"""
        mock_config.return_value = True

        result = self._call_create(
            type=23,  # seedance_2_0_image_to_video（人脸遮盖仅适配 Seedance 2.0 系列）
            image_path='start.png,end.png',
            reference_images=json.dumps(['ref.png']),
            video_path='clip.mp4',
        )

        self.assertEqual(result, 123)
        self.assertEqual(mock_create_step.call_count, 4)

        step_types = [call.kwargs['step_type'] for call in mock_create_step.call_args_list]
        self.assertEqual(step_types, [
            PipelineStepType.FACE_MASK,
            PipelineStepType.IMAGE_FACE_MASK,
            PipelineStepType.IMAGE_FACE_MASK,
            PipelineStepType.IMAGE_FACE_MASK,
        ])
        self.assertTrue(all(call.kwargs['stage'] == PipelineStage.PARAM_PREPARE for call in mock_create_step.call_args_list))

        params = [call.kwargs['params'] for call in mock_create_step.call_args_list]
        self.assertEqual(params[1]['field'], 'image_path')
        self.assertEqual(params[1]['index'], 0)
        self.assertEqual(params[2]['field'], 'image_path')
        self.assertEqual(params[2]['index'], 1)
        self.assertEqual(params[3]['field'], 'reference_images')
        self.assertEqual(params[3]['index'], 0)

    @patch('config.config_util.get_dynamic_config_value')
    @patch('config.constant.Edition.is_community', return_value=False)
    @patch('model.ai_tool_pipeline_steps.PipelineStepModel.create_in_transaction')
    @patch('model.database.execute_insert_in_transaction', return_value=123)
    @patch('model.database.transaction', return_value=_FakeTransaction())
    def test_image_face_mask_switch_off_skips_image_steps(
        self,
        mock_transaction,
        mock_insert,
        mock_create_step,
        mock_is_community,
        mock_config,
    ):
        """人脸遮罩总开关关闭时不创建图片遮罩步骤"""
        mock_config.return_value = False

        result = self._call_create(
            type=23,  # seedance_2_0_image_to_video
            image_path='start.png,end.png',
            reference_images=json.dumps(['ref.png']),
            video_path=None,
        )

        self.assertEqual(result, 123)
        mock_create_step.assert_not_called()

    @patch('config.config_util.get_dynamic_config_value')
    @patch('config.constant.Edition.is_community', return_value=False)
    @patch('model.ai_tool_pipeline_steps.PipelineStepModel.create_in_transaction')
    @patch('model.database.execute_insert_in_transaction', return_value=123)
    @patch('model.database.transaction', return_value=_FakeTransaction())
    def test_face_mask_switch_off_skips_video_steps(
        self,
        mock_transaction,
        mock_insert,
        mock_create_step,
        mock_is_community,
        mock_config,
    ):
        """人脸遮罩总开关关闭时，视频输入也不创建 face_mask 步骤"""
        mock_config.return_value = False

        result = self._call_create(type=23, video_path='clip.mp4')

        self.assertEqual(result, 123)
        mock_create_step.assert_not_called()

    @patch('config.config_util.get_dynamic_config_value')
    @patch('config.constant.Edition.is_community', return_value=False)
    @patch('model.ai_tool_pipeline_steps.PipelineStepModel.create_in_transaction')
    @patch('model.database.execute_insert_in_transaction', return_value=124)
    @patch('model.database.transaction', return_value=_FakeTransaction())
    def test_non_seedance_type_never_creates_face_mask_steps(
        self,
        mock_transaction,
        mock_insert,
        mock_create_step,
        mock_is_community,
        mock_config,
    ):
        """回归：非 Seedance 任务类型（如 H3 参考生视频 36）即使开关开启也不创建遮盖步骤"""
        mock_config.return_value = True  # 遮盖开关开

        result = self._call_create(
            type=37,
            image_path='start.png',
            reference_images=json.dumps(['ref.png']),
            video_path='clip.mp4',
        )

        self.assertEqual(result, 124)
        # H3 步骤允许存在，但绝不能出现人脸遮盖步骤
        step_types = [c.kwargs['step_type'] for c in mock_create_step.call_args_list]
        self.assertNotIn(PipelineStepType.FACE_MASK, step_types)
        self.assertNotIn(PipelineStepType.IMAGE_FACE_MASK, step_types)

    @patch('task.pipeline_drivers.PipelineDriverFactory.build_h3_prompt_optimize_step_configs')
    @patch('config.unified_config.UnifiedConfigRegistry.get_by_id')
    @patch('config.config_util.get_dynamic_config_value')
    @patch('config.constant.Edition.is_community', return_value=False)
    @patch('model.ai_tool_pipeline_steps.PipelineStepModel.create_in_transaction')
    @patch('model.database.execute_insert_in_transaction', return_value=456)
    @patch('model.database.transaction', return_value=_FakeTransaction())
    def test_creates_h3_prompt_optimize_step_with_chat_model(
        self,
        mock_transaction,
        mock_insert,
        mock_create_step,
        mock_is_community,
        mock_config,
        mock_get_by_id,
        mock_build,
    ):
        """H3 图生视频：原子创建 H3_PROMPT_OPTIMIZE 步骤并透传对话模型"""
        from types import SimpleNamespace
        mock_config.return_value = False  # Seedance 关闭，专注 H3 分支
        mock_get_by_id.return_value = SimpleNamespace(key='minimax_h3_image_to_video')
        mock_build.return_value = [{
            'step_type': PipelineStepType.H3_PROMPT_OPTIMIZE,
            'params': {'variant': 'I2VA', 'original_prompt': 'p', 'duration': 5,
                       'chat_model': 'qwen-plus', 'chat_vendor_id': 3},
            'target': 'I2VA',
        }]

        result = self._call_create(
            type=34, image_path='a.png',
            h3_chat_model='qwen-plus', h3_chat_vendor_id=3,
        )

        self.assertEqual(result, 456)
        # build 收到 chat_model / chat_vendor_id
        _, kwargs = mock_build.call_args
        self.assertEqual(kwargs.get('chat_model'), 'qwen-plus')
        self.assertEqual(kwargs.get('chat_vendor_id'), 3)
        # 创建了 1 个 H3 步骤
        self.assertEqual(mock_create_step.call_count, 1)
        step_call = mock_create_step.call_args
        self.assertEqual(step_call.kwargs['step_type'], PipelineStepType.H3_PROMPT_OPTIMIZE)
        self.assertEqual(step_call.kwargs['params']['chat_model'], 'qwen-plus')

    @patch('task.pipeline_drivers.PipelineDriverFactory.build_h3_prompt_optimize_step_configs')
    @patch('config.unified_config.UnifiedConfigRegistry.get_by_id')
    @patch('config.config_util.get_dynamic_config_value')
    @patch('config.constant.Edition.is_community', return_value=False)
    @patch('model.ai_tool_pipeline_steps.PipelineStepModel.create_in_transaction')
    @patch('model.database.execute_insert_in_transaction', return_value=457)
    @patch('model.database.transaction', return_value=_FakeTransaction())
    def test_creates_h3_prompt_optimize_step_for_reference_type(
        self,
        mock_transaction,
        mock_insert,
        mock_create_step,
        mock_is_community,
        mock_config,
        mock_get_by_id,
        mock_build,
    ):
        """H3 参考生视频：原子创建 H3_PROMPT_OPTIMIZE 步骤，透传 task_key 与音视频参考字段"""
        from types import SimpleNamespace
        mock_config.return_value = False  # Seedance 关闭，专注 H3 分支
        mock_get_by_id.return_value = SimpleNamespace(key='minimax_h3_reference_to_video')
        mock_build.return_value = [{
            'step_type': PipelineStepType.H3_PROMPT_OPTIMIZE,
            'params': {'variant': 'Ref2VA', 'original_prompt': 'p', 'duration': 8,
                       'ref_counts': {'images': 2, 'videos': 1, 'audios': 1}},
            'target': 'Ref2VA',
        }]

        result = self._call_create(
            type=37, duration=8,
            reference_images=json.dumps(['r1.png', 'r2.png']),
            video_path='v1.mp4', audio_path='a1.wav',
        )

        self.assertEqual(result, 457)
        # build 收到 task_key，命名空间带参考视频/音频（供 Ref2VA 资产计数）
        args, kwargs = mock_build.call_args
        self.assertEqual(kwargs.get('task_key'), 'minimax_h3_reference_to_video')
        ns = args[0]
        self.assertEqual(ns.video_path, 'v1.mp4')
        self.assertEqual(ns.audio_path, 'a1.wav')
        self.assertEqual(mock_create_step.call_count, 1)
        step_call = mock_create_step.call_args
        self.assertEqual(step_call.kwargs['step_type'], PipelineStepType.H3_PROMPT_OPTIMIZE)
        self.assertEqual(step_call.kwargs['params']['variant'], 'Ref2VA')

    @patch('model.database.execute_update_in_transaction')
    @patch('config.unified_config.UnifiedConfigRegistry.get_by_id', return_value=None)
    @patch('config.config_util.get_dynamic_config_value')
    @patch('config.constant.Edition.is_community', return_value=False)
    @patch('model.ai_tool_pipeline_steps.PipelineStepModel.create_in_transaction')
    @patch('model.database.execute_insert_in_transaction', return_value=789)
    @patch('model.database.transaction', return_value=_FakeTransaction())
    def test_no_steps_resets_status_to_pending(
        self,
        mock_transaction,
        mock_insert,
        mock_create_step,
        mock_is_community,
        mock_config,
        mock_get_by_id,
        mock_update,
    ):
        """普通任务（无 param_prepare 步骤）：事务内回退 PENDING，避免卡在 WAITING_PARAM_PREPARE"""
        from config.constant import AI_TOOL_STATUS_PENDING
        mock_config.return_value = False  # Seedance 关闭；get_by_id 返回 None → 不进 H3 分支

        result = self._call_create(type=100, status=4)  # 4 = WAITING_PARAM_PREPARE

        self.assertEqual(result, 789)
        mock_create_step.assert_not_called()
        mock_update.assert_called_once()
        sql_arg = mock_update.call_args.args[1]
        self.assertIn('UPDATE ai_tools SET status', sql_arg)
        self.assertEqual(mock_update.call_args.args[2][0], AI_TOOL_STATUS_PENDING)


if __name__ == '__main__':
    unittest.main()
