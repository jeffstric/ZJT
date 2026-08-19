"""
face_mask_prompt 单元测试

覆盖黑框还原句的幂等追加（ensure）/ 精确移除（strip）/ 检测（contains）与
「素材实际遮盖状态」判断（has_applied_face_mask），重点验证：
- 还原句唯一写入方是 ensure（常量原文），strip 为其精确逆变换，基线原样恢复
- 供应商轮换场景：提示词内容始终跟随 pipeline steps 的实际遮盖状态
- LLM 变体表述不在处理范围内（提示词基线由 SKILL 约束不写黑框描述）
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from task.visual_drivers import face_mask_prompt
from task.visual_drivers.face_mask_prompt import (
    contains_face_mask_hint,
    ensure_face_mask_hint,
    has_applied_face_mask,
    strip_face_mask_hint,
)
from config.constant import FaceMaskPromptConstants
from model.ai_tool_pipeline_steps import PipelineStepStatus, PipelineStepType

RESTORE_HINT = FaceMaskPromptConstants.RESTORE_HINT
JOINER = FaceMaskPromptConstants.HINT_JOINER


def _step(step_type=PipelineStepType.FACE_MASK, status=PipelineStepStatus.COMPLETED,
          result_url='upload/face_mask/masked.mp4', target='upload/temp/src.mp4'):
    return SimpleNamespace(step_type=step_type, status=status,
                           result_url=result_url, target=target)


def _ai_tool(ai_tool_id=101):
    return SimpleNamespace(id=ai_tool_id)


class TestContainsFaceMaskHint(unittest.TestCase):

    def test_exact_hint(self):
        self.assertTrue(contains_face_mask_hint(f'参考视频1的内容进行视频复刻{JOINER}{RESTORE_HINT}'))

    def test_variant_not_matched(self):
        # 变体表述不视为还原句：唯一合法写入方是 ensure 的常量原文
        self.assertFalse(contains_face_mask_hint('把黑色方块换成真真人脸。'))

    def test_normal_prompt(self):
        self.assertFalse(contains_face_mask_hint('参考视频1的内容进行视频复刻。'))
        self.assertFalse(contains_face_mask_hint('人脸清晰自然，画面精美。'))

    def test_empty(self):
        self.assertFalse(contains_face_mask_hint(''))
        self.assertFalse(contains_face_mask_hint(None))


class TestStripFaceMaskHint(unittest.TestCase):

    def test_strip_comma_joined_restores_base(self):
        # ensure 逗号衔接形态的精确逆变换：基线原样恢复
        prompt = f'参考视频1的内容进行视频复刻{JOINER}{RESTORE_HINT}'
        self.assertEqual(strip_face_mask_hint(prompt), '参考视频1的内容进行视频复刻')

    def test_strip_after_terminator_restores_base(self):
        prompt = f'参考视频1的内容进行视频复刻。{RESTORE_HINT}'
        self.assertEqual(strip_face_mask_hint(prompt), '参考视频1的内容进行视频复刻。')

    def test_strip_pure_hint_to_empty(self):
        self.assertEqual(strip_face_mask_hint(RESTORE_HINT), '')

    def test_no_dangling_punctuation(self):
        # 逗号衔接形态移除后不得残留悬挂逗号
        prompt = f'参考视频1的内容进行视频复刻，带货商品为图片1{JOINER}{RESTORE_HINT}'
        self.assertEqual(strip_face_mask_hint(prompt), '参考视频1的内容进行视频复刻，带货商品为图片1')

    def test_variant_not_stripped(self):
        variant = '参考视频1的内容进行视频复刻，把黑色方块换成真真人脸。'
        self.assertEqual(strip_face_mask_hint(variant), variant)

    def test_normal_prompt_with_face_words_unchanged(self):
        prompt = '人脸清晰自然，画面精美，人物表情生动。'
        self.assertEqual(strip_face_mask_hint(prompt), prompt)

    def test_idempotent(self):
        prompt = f'参考视频1的内容进行视频复刻{JOINER}{RESTORE_HINT}'
        once = strip_face_mask_hint(prompt)
        self.assertEqual(strip_face_mask_hint(once), once)

    def test_no_match_returns_unchanged(self):
        self.assertEqual(strip_face_mask_hint('参考视频1的内容进行视频复刻。'),
                         '参考视频1的内容进行视频复刻。')
        self.assertEqual(strip_face_mask_hint(''), '')


class TestHasAppliedFaceMask(unittest.TestCase):

    def test_completed_face_mask_step(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=[_step()]):
            self.assertTrue(has_applied_face_mask(_ai_tool()))

    def test_completed_image_face_mask_step(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=[_step(step_type=PipelineStepType.IMAGE_FACE_MASK)]):
            self.assertTrue(has_applied_face_mask(_ai_tool()))

    def test_failed_step_not_applied(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=[_step(status=PipelineStepStatus.FAILED)]):
            self.assertFalse(has_applied_face_mask(_ai_tool()))

    def test_step_without_result_url_not_applied(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=[_step(result_url=None)]):
            self.assertFalse(has_applied_face_mask(_ai_tool()))

    def test_other_step_type_ignored(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=[_step(step_type=PipelineStepType.IMPLEMENTATION_RETRY)]):
            self.assertFalse(has_applied_face_mask(_ai_tool()))

    def test_no_steps(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=None):
            self.assertFalse(has_applied_face_mask(_ai_tool()))

    def test_query_exception_falls_back_to_false(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          side_effect=RuntimeError('db down')):
            self.assertFalse(has_applied_face_mask(_ai_tool()))


class TestEnsureFaceMaskHint(unittest.TestCase):

    def test_appends_when_masked_and_absent(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=[_step()]):
            result = ensure_face_mask_hint('参考视频1的内容进行视频复刻', _ai_tool())
        self.assertEqual(result, f'参考视频1的内容进行视频复刻{JOINER}{RESTORE_HINT}')

    def test_appends_directly_after_terminator(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=[_step()]):
            result = ensure_face_mask_hint('参考视频1的内容进行视频复刻。', _ai_tool())
        self.assertEqual(result, f'参考视频1的内容进行视频复刻。{RESTORE_HINT}')

    def test_idempotent_when_hint_present(self):
        prompt = f'参考视频1的内容进行视频复刻{JOINER}{RESTORE_HINT}'
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=[_step()]):
            self.assertEqual(ensure_face_mask_hint(prompt, _ai_tool()), prompt)

    def test_fills_empty_prompt(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=[_step()]):
            self.assertEqual(ensure_face_mask_hint('', _ai_tool()), RESTORE_HINT)

    def test_unchanged_when_not_masked(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=None):
            prompt = '参考视频1的内容进行视频复刻'
            self.assertEqual(ensure_face_mask_hint(prompt, _ai_tool()), prompt)

    def test_unchanged_on_query_failure(self):
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          side_effect=RuntimeError('db down')):
            prompt = '参考视频1的内容进行视频复刻'
            self.assertEqual(ensure_face_mask_hint(prompt, _ai_tool()), prompt)


class TestSupplierRotationConsistency(unittest.TestCase):
    """供应商轮换（跨实现方重试）下提示词与素材状态保持一致"""

    def test_volcengine_to_huimengi_rotation_restores_base(self):
        # volcengine 执行：遮盖完成，ensure 追加常量原文
        base = '参考视频1的内容进行视频复刻'
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=[_step()]):
            after_ensure = ensure_face_mask_hint(base, _ai_tool())
        self.assertIn(RESTORE_HINT, after_ensure)
        # 重试到 huimengi：使用原始素材，strip 精确逆变换回到基线
        self.assertEqual(strip_face_mask_hint(after_ensure), base)

    def test_huimengi_to_volcengine_rotation(self):
        # huimengi 执行：无遮盖步骤，提示词保持基线
        base = '参考视频1的内容进行视频复刻'
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=None):
            after_huimengi = strip_face_mask_hint(base)
        self.assertEqual(after_huimengi, base)
        # 重试到 volcengine：仍无遮盖步骤，不追加，提示词与素材（原始）一致
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=None):
            self.assertEqual(ensure_face_mask_hint(after_huimengi, _ai_tool()), base)

    def test_volcengine_to_kkidc_rotation_keeps_hint(self):
        # volcengine 遮盖后重试到 kkidc：steps 保留，ensure 幂等不重复追加
        prompt = f'参考视频1的内容进行视频复刻{JOINER}{RESTORE_HINT}'
        with patch.object(face_mask_prompt.PipelineStepModel, 'get_by_ai_tool_and_stage',
                          return_value=[_step()]):
            self.assertEqual(ensure_face_mask_hint(prompt, _ai_tool()), prompt)


if __name__ == '__main__':
    unittest.main()
