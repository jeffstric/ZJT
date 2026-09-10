"""output_token_budget.resolve_max_output_tokens 单元测试

覆盖：默认值、DB 值透传、静态封顶、按剩余上下文动态收缩、下限兜底。
"""
import os
import sys
import unittest
from types import SimpleNamespace

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from config.constant import (
    AGENT_LLM_CONTEXT_SAFETY_MARGIN_TOKENS,
    AGENT_LLM_MAX_OUTPUT_TOKENS_CAP,
    AGENT_LLM_MIN_OUTPUT_TOKENS,
)
from script_writer_core.agents.output_token_budget import resolve_max_output_tokens


class TestResolveMaxOutputTokens(unittest.TestCase):

    def test_no_model_uses_default_capped(self):
        # 默认值 65536 同样受静态上限约束
        self.assertEqual(resolve_max_output_tokens(None, 0), AGENT_LLM_MAX_OUTPUT_TOKENS_CAP)

    def test_db_value_below_cap_passes_through(self):
        model = SimpleNamespace(max_output_tokens=8192, context_window=128000)
        self.assertEqual(resolve_max_output_tokens(model, 10000), 8192)

    def test_db_value_above_cap_is_capped(self):
        # 事故场景：deepseek-v4-flash-vision-exp 的 DB 值为 384000
        model = SimpleNamespace(max_output_tokens=384000, context_window=1000000)
        self.assertEqual(
            resolve_max_output_tokens(model, 10000), AGENT_LLM_MAX_OUTPUT_TOKENS_CAP
        )

    def test_dynamic_shrink_by_remaining_context(self):
        # 64K 小上下文模型：输入已占 4 万，剩余不足 32768，按剩余收缩
        model = SimpleNamespace(max_output_tokens=32768, context_window=65536)
        expected = 65536 - 40000 - AGENT_LLM_CONTEXT_SAFETY_MARGIN_TOKENS
        result = resolve_max_output_tokens(model, 40000)
        self.assertEqual(result, max(expected, AGENT_LLM_MIN_OUTPUT_TOKENS))
        self.assertLess(result, 32768)

    def test_dynamic_shrink_not_applied_when_plenty_remaining(self):
        # 1M 上下文 + 输入 10 万：剩余远大于静态上限，不触发动态收缩
        model = SimpleNamespace(max_output_tokens=384000, context_window=1000000)
        self.assertEqual(
            resolve_max_output_tokens(model, 100000), AGENT_LLM_MAX_OUTPUT_TOKENS_CAP
        )

    def test_min_output_floor_when_context_nearly_full(self):
        # 上下文接近占满：剩余为负时兜底下限，保证模型仍能短回复
        model = SimpleNamespace(max_output_tokens=32768, context_window=65536)
        self.assertEqual(
            resolve_max_output_tokens(model, 65000), AGENT_LLM_MIN_OUTPUT_TOKENS
        )

    def test_no_context_window_falls_back_to_static_cap(self):
        model = SimpleNamespace(max_output_tokens=384000, context_window=None)
        self.assertEqual(
            resolve_max_output_tokens(model, 900000), AGENT_LLM_MAX_OUTPUT_TOKENS_CAP
        )

    def test_missing_max_output_tokens_uses_default_capped(self):
        model = SimpleNamespace(max_output_tokens=None, context_window=None)
        self.assertEqual(resolve_max_output_tokens(model, 0), AGENT_LLM_MAX_OUTPUT_TOKENS_CAP)


if __name__ == '__main__':
    unittest.main()
