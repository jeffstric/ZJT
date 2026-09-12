"""火山方舟 404（InvalidEndpointOrModel.NotFound）错误翻译测试。

背景（2026-09-12 线上事故）：火山账号未开通 deepseek-v4-flash，vendor_model
关联仍存在，任务创建成功但 LLM 调用持续 404；上层只见英文 404，用户无从
知道该换供应商或去方舟控制台开通。VolcengineOpenAIClient 覆写
_humanize_api_error 把该错误翻译为可操作的中文提示后上抛。
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


class TestVolcengineModelNameMap(unittest.TestCase):
    """方舟托管的 DeepSeek 为官方同源模型，模型名跟随官方体系。

    2026-09 官方下线 deepseek-v4-flash 旧名（由 deepseek-flash 提供服务），
    方舟同步下线旧名；火山客户端映射必须与官方客户端（openai_deepseek.py）
    同步，否则调用 404（本次事故根因）。
    """

    def test_flash_maps_to_official_new_name(self):
        client = VolcengineOpenAIClient.__new__(VolcengineOpenAIClient)
        self.assertEqual(client._resolve_model_name("deepseek-v4-flash"), "deepseek-flash")
        self.assertEqual(client._resolve_model_name("deepseek-v4-flash-vision-exp"), "deepseek-flash")

    def test_pro_name_unchanged(self):
        client = VolcengineOpenAIClient.__new__(VolcengineOpenAIClient)
        self.assertEqual(client._resolve_model_name("deepseek-v4-pro"), "deepseek-v4-pro")

    def test_doubao_version_suffix_mapping_kept(self):
        client = VolcengineOpenAIClient.__new__(VolcengineOpenAIClient)
        self.assertEqual(
            client._resolve_model_name("doubao-seed-2-0-pro"), "doubao-seed-2-0-pro-260215"
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
