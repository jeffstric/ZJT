"""小米 MiMo 客户端与路由测试。

V2.6 系列（mimo-v2.6-flash / mimo-v2.6-pro）复用已有 mimo 供应商与
OpenAI 兼容端点，API model ID 与 model 表友好名称一致。
前缀 'mimo' 覆盖 V2.5 / V2.6 全系。
"""
import os
import sys
import unittest

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from config.constant import LLMModel, LLMVendor
from llm.llm_client_factory import LLMClientFactory
from llm.openai_mimo import MimoOpenAIClient


class TestMimoModelNameResolve(unittest.TestCase):
    def test_v25_and_v26_passthrough(self):
        client = MimoOpenAIClient.__new__(MimoOpenAIClient)
        for name in (
            LLMModel.MIMO_V2_5,
            LLMModel.MIMO_V2_5_PRO,
            LLMModel.MIMO_V2_6_FLASH,
            LLMModel.MIMO_V2_6_PRO,
        ):
            self.assertEqual(client._resolve_model_name(name), name)

    def test_v26_constant_values(self):
        self.assertEqual(LLMModel.MIMO_V2_6_FLASH, "mimo-v2.6-flash")
        self.assertEqual(LLMModel.MIMO_V2_6_PRO, "mimo-v2.6-pro")


class TestMimoThinkingParams(unittest.TestCase):
    def _client(self):
        client = MimoOpenAIClient.__new__(MimoOpenAIClient)
        client.vendor_name = "mimo"
        client.thinking_mode = "enable_thinking"
        return client

    def test_thinking_enabled_sends_extra_body(self):
        client = self._client()
        kwargs = {"model": LLMModel.MIMO_V2_6_PRO}
        client._apply_thinking_params(kwargs, True, "high")
        self.assertEqual(kwargs["extra_body"]["thinking"]["type"], "enabled")
        self.assertEqual(kwargs["reasoning_effort"], "high")

    def test_thinking_disabled_sends_disabled_type(self):
        client = self._client()
        kwargs = {"model": LLMModel.MIMO_V2_6_FLASH}
        client._apply_thinking_params(kwargs, False, "high")
        self.assertEqual(kwargs["extra_body"]["thinking"]["type"], "disabled")


class TestMimoRouting(unittest.TestCase):
    def test_v26_models_route_to_mimo(self):
        for name in (LLMModel.MIMO_V2_6_FLASH, LLMModel.MIMO_V2_6_PRO, LLMModel.MIMO_V2_5):
            self.assertEqual(
                LLMClientFactory._get_vendor_by_model(name),
                LLMVendor.MIMO,
            )


if __name__ == "__main__":
    unittest.main()
