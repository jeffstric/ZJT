"""智谱 BigModel 国内站（glmcn）客户端与路由测试。

背景：GLM-5.3 始终启用思考（服务端无法关闭），reasoning_effort 仅支持
low/high/max（无 "medium"）；前端思考强度沿用 low/medium/high 三档，需经
LLMModel.GLM_REASONING_EFFORT_MAP 映射。本供应商下全部模型均为 GLM 系列，
GlmcnOpenAIClient._apply_thinking_params 不做模型前缀区分。
路由：glm-5.3 → glmcn；火山方舟 glm-5.3-flash 前缀更长、先命中先路由，
不得被 'glm' 通配项抢走到 glmcn。
"""
import os
import sys
import unittest

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from config.constant import LLMVendor
from llm.llm_client_factory import LLMClientFactory
from llm.openai_glmcn import GlmcnOpenAIClient


class TestGlmcnModelNameResolve(unittest.TestCase):
    def test_model_id_passthrough(self):
        """BigModel 官方 API model ID 即 glm-5.3，无需版本后缀映射"""
        client = GlmcnOpenAIClient.__new__(GlmcnOpenAIClient)
        self.assertEqual(client._resolve_model_name("glm-5.3"), "glm-5.3")


class TestGlmcnThinkingParams(unittest.TestCase):
    def _client(self):
        client = GlmcnOpenAIClient.__new__(GlmcnOpenAIClient)
        client.vendor_name = "glmcn"
        client.thinking_mode = "reasoning_effort"
        return client

    def test_effort_mapped_low_medium_high(self):
        """前端三档映射为 GLM 的 low/high/max，保持强度单调"""
        client = self._client()
        for front, glm in (("low", "low"), ("medium", "high"), ("high", "max")):
            kwargs = {"model": "glm-5.3"}
            client._apply_thinking_params(kwargs, True, front)
            self.assertEqual(kwargs["reasoning_effort"], glm)

    def test_max_passthrough(self):
        client = self._client()
        kwargs = {"model": "glm-5.3"}
        client._apply_thinking_params(kwargs, True, "max")
        self.assertEqual(kwargs["reasoning_effort"], "max")

    def test_thinking_disabled_sends_no_effort(self):
        """关闭思考时不发参数（GLM 服务端仍会思考，属模型固有行为）"""
        client = self._client()
        kwargs = {"model": "glm-5.3"}
        client._apply_thinking_params(kwargs, False, "high")
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertNotIn("extra_body", kwargs)


class TestGlmcnRouting(unittest.TestCase):
    def test_glm_5_3_routes_to_glmcn(self):
        self.assertEqual(
            LLMClientFactory._get_vendor_by_model("glm-5.3"),
            LLMVendor.GLMCN,
        )

    def test_glm_5_3_flash_still_routes_to_volcengine(self):
        """前缀重叠回归：glm-5.3-flash 以 glm-5.3 开头，必须先命中方舟专属前缀"""
        self.assertEqual(
            LLMClientFactory._get_vendor_by_model("glm-5.3-flash"),
            LLMVendor.VOLCENGINE,
        )


if __name__ == "__main__":
    unittest.main()
