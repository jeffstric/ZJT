"""火山方舟 GLM-5.3 思考强度映射测试。

背景：GLM-5.3 始终启用思考（thinking.type 仅支持 enabled，默认即开），
reasoning_effort 仅支持 low/high/max（无 "medium"，默认 max）；前端思考
强度沿用 low/medium/high 三档，直传 medium 会被方舟拒绝。
VolcengineOpenAIClient._apply_thinking_params 覆写按实际 API model ID 的
glm 前缀识别并经 LLMModel.GLM_REASONING_EFFORT_MAP 映射。
"""
import os
import sys
import unittest

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from llm.volcengine_openai_client import VolcengineOpenAIClient


class TestVolcengineGlmModelNameMap(unittest.TestCase):
    def test_glm_5_3_flash_maps_to_versioned_id(self):
        client = VolcengineOpenAIClient.__new__(VolcengineOpenAIClient)
        self.assertEqual(
            client._resolve_model_name("glm-5.3-flash"),
            "glm-5-3-flash-260828",
        )


class TestVolcengineGlmThinkingParams(unittest.TestCase):
    def _client(self):
        client = VolcengineOpenAIClient.__new__(VolcengineOpenAIClient)
        client.vendor_name = "volcengine"
        client.thinking_mode = "reasoning_effort"
        return client

    def test_glm_effort_mapped_low_medium_high(self):
        """前端三档映射为 GLM 的 low/high/max，保持强度单调"""
        client = self._client()
        for front, ark in (("low", "low"), ("medium", "high"), ("high", "max")):
            kwargs = {"model": "glm-5-3-flash-260828"}
            client._apply_thinking_params(kwargs, True, front)
            self.assertEqual(kwargs["reasoning_effort"], ark)

    def test_glm_max_passthrough(self):
        client = self._client()
        kwargs = {"model": "glm-5-3-flash-260828"}
        client._apply_thinking_params(kwargs, True, "max")
        self.assertEqual(kwargs["reasoning_effort"], "max")

    def test_glm_thinking_disabled_sends_no_effort(self):
        """关闭思考时不发参数（GLM 服务端仍会思考，属模型固有行为）"""
        client = self._client()
        kwargs = {"model": "glm-5-3-flash-260828"}
        client._apply_thinking_params(kwargs, False, "high")
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertNotIn("extra_body", kwargs)

    def test_non_glm_models_keep_base_behavior(self):
        """doubao / deepseek 仍走基类：reasoning_effort 直传不映射"""
        client = self._client()
        for model in ("doubao-seed-2-0-lite-260215", "deepseek-v4-flash-ga-260731"):
            kwargs = {"model": model}
            client._apply_thinking_params(kwargs, True, "medium")
            self.assertEqual(kwargs["reasoning_effort"], "medium")


if __name__ == "__main__":
    unittest.main()
