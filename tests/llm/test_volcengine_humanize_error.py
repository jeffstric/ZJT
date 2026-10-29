"""火山方舟 404/400（NotFound / ClosedEndpoint）错误翻译测试。

背景一（2026-09-12 线上事故）：火山账号未开通 deepseek-v4-flash，vendor_model
关联仍存在，任务创建成功但 LLM 调用持续 404；上层只见英文 404，用户无从
知道该换供应商或去方舟控制台开通。VolcengineOpenAIClient 覆写
_humanize_api_error 把该错误翻译为可操作的中文提示后上抛。

背景二（2026-10-25 线上事故）：方舟下线 doubao-seed-2-0-lite-260215 快照，
调用持续 400 InvalidEndpoint.ClosedEndpoint，营销 PM agent 全量失败；
映射改为实测可用的 260428，并把该错误码同样翻译为中文提示。
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from llm.openai_base_client import OpenAIBaseClient
from llm.volcengine_openai_client import VolcengineOpenAIClient


ARK_404 = Exception(
    "Error code: 404 - {'error': {'code': 'InvalidEndpointOrModel.NotFound', "
    "'message': 'The model or endpoint deepseek-v4-flash does not exist or you "
    "do not have access to it.', 'type': 'Not Found'}}"
)

# 2026-10-25 线上事故：方舟下线 doubao-seed-2-0-lite-260215 快照，
# 调用返回 400 InvalidEndpoint.ClosedEndpoint，营销 PM agent 100% 失败
ARK_CLOSED = Exception(
    "Error code: 400 - {'error': {'code': 'InvalidEndpoint.ClosedEndpoint', "
    "'message': 'The request targeted an endpoint that is currently closed or "
    "temporarily unavailable. Request id: 02179301507751448', 'type': 'Bad Request'}}"
)


class TestVolcengineModelNameMap(unittest.TestCase):
    """方舟目录的 DeepSeek 模型 ID 全部带版本后缀，不存在任何裸名。

    裸名（deepseek-v4-flash / deepseek-flash 等）调用必然 404
    InvalidEndpointOrModel.NotFound；映射目标须为方舟实测 200 的
    带版本 ID（2026-09-13 生产 key 实测）。
    """

    def test_flash_maps_to_ga_versioned_id(self):
        client = VolcengineOpenAIClient.__new__(VolcengineOpenAIClient)
        self.assertEqual(
            client._resolve_model_name("deepseek-v4-flash"),
            "deepseek-v4-flash-ga-260731",
        )
        # 方舟无 vision 变体，ga 版实测支持图片输入，作为 vision-exp 的替代
        self.assertEqual(
            client._resolve_model_name("deepseek-v4-flash-vision-exp"),
            "deepseek-v4-flash-ga-260731",
        )

    def test_pro_maps_to_ga_versioned_id(self):
        client = VolcengineOpenAIClient.__new__(VolcengineOpenAIClient)
        self.assertEqual(
            client._resolve_model_name("deepseek-v4-pro"),
            "deepseek-v4-pro-ga-260813",
        )

    def test_doubao_version_suffix_mapping_kept(self):
        client = VolcengineOpenAIClient.__new__(VolcengineOpenAIClient)
        self.assertEqual(
            client._resolve_model_name("doubao-seed-2-0-pro"), "doubao-seed-2-0-pro-260215"
        )

    def test_doubao_lite_maps_to_live_snapshot(self):
        """260215 快照已被方舟下线（2026-10-24 前后，ClosedEndpoint 400），
        映射目标须为生产 key 实测 200 的快照（2026-10-26 实测 260428 可用）。
        """
        client = VolcengineOpenAIClient.__new__(VolcengineOpenAIClient)
        self.assertEqual(
            client._resolve_model_name("doubao-seed-2-0-lite"),
            "doubao-seed-2-0-lite-260428",
        )


class TestVolcengineHumanizeApiError(unittest.TestCase):
    def _client(self):
        client = VolcengineOpenAIClient.__new__(VolcengineOpenAIClient)
        client.api_key = "ark-test123456"
        client.base_url = "https://ark.cn-beijing.volces.com/api/v3"
        client.vendor_name = "volcengine"
        client.thinking_mode = "reasoning_effort"
        return client

    def test_not_found_translated_with_model_name(self):
        humanized = self._client()._humanize_api_error(ARK_404, model="deepseek-v4-flash")
        self.assertIsNotNone(humanized)
        self.assertIn("deepseek-v4-flash", humanized)
        self.assertIn("InvalidEndpointOrModel.NotFound", humanized)
        self.assertIn("火山方舟", humanized)

    def test_closed_endpoint_translated_with_model_name(self):
        humanized = self._client()._humanize_api_error(ARK_CLOSED, model="doubao-seed-2-0-lite")
        self.assertIsNotNone(humanized)
        self.assertIn("doubao-seed-2-0-lite", humanized)
        self.assertIn("InvalidEndpoint.ClosedEndpoint", humanized)
        self.assertIn("_MODEL_NAME_MAP", humanized)
        self.assertIn("已被官方下线", humanized)

    def test_other_errors_passthrough(self):
        client = self._client()
        self.assertIsNone(client._humanize_api_error(Exception("timeout"), model="doubao-seed-2-0-lite"))
        self.assertIsNone(client._humanize_api_error(Exception("Error code: 429 - rate limit"), model="x"))

    def test_base_default_hook_is_none(self):
        client = OpenAIBaseClient.__new__(OpenAIBaseClient)
        self.assertIsNone(client._humanize_api_error(ARK_404, model="deepseek-v4-flash"))

    def test_call_api_raises_humanized_message(self):
        """call_api 内翻译生效：上抛异常为中文提示，原始错误保留为 __cause__"""
        client = self._client()
        with patch('llm.openai_base_client.OpenAI') as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.side_effect = ARK_404

            with patch('llm.openai_base_client._get_llm_logger') as mock_get_logger:
                mock_get_logger.return_value = MagicMock()

                with self.assertRaises(Exception) as ctx:
                    client.call_api(
                        model="deepseek-v4-flash",
                        messages=[{"role": "user", "content": "hi"}],
                    )

        self.assertIn("火山方舟账号未开通", str(ctx.exception))
        self.assertIn("deepseek-v4-flash", str(ctx.exception))
        self.assertIs(ctx.exception.__cause__, ARK_404)


if __name__ == "__main__":
    unittest.main()
