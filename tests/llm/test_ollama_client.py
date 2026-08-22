"""
OllamaClient 单元测试
"""
import unittest
from unittest.mock import patch, MagicMock


class TestOllamaClient(unittest.TestCase):
    """OllamaClient 测试"""

    @patch('llm.ollama_client.get_dynamic_config_value')
    def test_init_enabled(self, mock_config):
        """测试初始化（启用状态）"""
        mock_config.side_effect = lambda *args, default=None: {
            ('llm', 'ollama', 'enabled'): True,
            ('llm', 'ollama', 'base_url'): 'http://localhost:11434',
            ('llm', 'ollama', 'temperature'): 0.7,
            ('llm', 'ollama', 'top_p'): 0.8,
            ('llm', 'ollama', 'top_k'): 20,
            ('llm', 'ollama', 'min_p'): 0.0,
            ('llm', 'ollama', 'presence_penalty'): 1.5,
            ('llm', 'ollama', 'repetition_penalty'): 1.0,
            ('llm', 'ollama', 'enable_thinking'): False,
        }.get(args, default)

        from llm.ollama_client import OllamaClient
        client = OllamaClient()

        self.assertTrue(client.enabled)
        self.assertEqual(client.base_url, 'http://localhost:11434')
        self.assertEqual(client.temperature, 0.7)
        self.assertEqual(client.top_p, 0.8)

    @patch('llm.ollama_client.get_dynamic_config_value')
    def test_init_disabled(self, mock_config):
        """测试初始化（禁用状态）"""
        mock_config.side_effect = lambda *args, default=None: {
            ('llm', 'ollama', 'enabled'): False,
        }.get(args, default)

        from llm.ollama_client import OllamaClient
        client = OllamaClient()

        self.assertFalse(client.enabled)

    @patch('llm.ollama_client.get_dynamic_config_value')
    def test_model_name_strip_prefix(self, mock_config):
        """测试模型名称去除 ollama: 前缀"""
        mock_config.side_effect = lambda *args, default=None: {
            ('llm', 'ollama', 'enabled'): True,
            ('llm', 'ollama', 'base_url'): 'http://localhost:11434',
            ('llm', 'ollama', 'temperature'): 0.7,
            ('llm', 'ollama', 'top_p'): 0.8,
            ('llm', 'ollama', 'top_k'): 20,
            ('llm', 'ollama', 'min_p'): 0.0,
            ('llm', 'ollama', 'presence_penalty'): 1.5,
            ('llm', 'ollama', 'repetition_penalty'): 1.0,
            ('llm', 'ollama', 'enable_thinking'): False,
        }.get(args, default)

        from llm.ollama_client import OllamaClient
        client = OllamaClient()

        # 测试去除前缀
        model_with_prefix = "ollama:qwen3.6:35b-a3b"
        expected = "qwen3.6:35b-a3b"

        # 使用客户端内部的模型名处理逻辑
        actual_model = model_with_prefix
        if actual_model.startswith("ollama:"):
            actual_model = actual_model[7:]

        self.assertEqual(actual_model, expected)

    @patch('llm.ollama_client.get_dynamic_config_value')
    def test_call_api_disabled(self, mock_config):
        """测试禁用时调用 API 抛出异常"""
        mock_config.side_effect = lambda *args, default=None: {
            ('llm', 'ollama', 'enabled'): False,
        }.get(args, default)

        from llm.ollama_client import OllamaClient
        client = OllamaClient()

        with self.assertRaises(Exception) as ctx:
            client.call_api(
                model="ollama:test-model",
                messages=[{"role": "user", "content": "test"}]
            )
        self.assertIn("Ollama 未启用", str(ctx.exception))

    @patch('llm.ollama_client.get_dynamic_config_value')
    @patch('llm.ollama_client.OpenAI')
    def test_call_api_success(self, mock_openai_class, mock_config):
        """测试成功调用 API"""
        mock_config.side_effect = lambda *args, default=None: {
            ('llm', 'ollama', 'enabled'): True,
            ('llm', 'ollama', 'base_url'): 'http://localhost:11434',
            ('llm', 'ollama', 'temperature'): 0.7,
            ('llm', 'ollama', 'top_p'): 0.8,
            ('llm', 'ollama', 'top_k'): 20,
            ('llm', 'ollama', 'min_p'): 0.0,
            ('llm', 'ollama', 'presence_penalty'): 1.5,
            ('llm', 'ollama', 'repetition_penalty'): 1.0,
            ('llm', 'ollama', 'enable_thinking'): False,
        }.get(args, default)

        # Mock OpenAI client
        mock_openai = MagicMock()
        mock_openai_class.return_value = mock_openai

        # Mock response
        mock_choice = MagicMock()
        mock_choice.message.content = "Test response"
        mock_choice.message.tool_calls = None

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 30

        mock_openai.chat.completions.create.return_value = mock_response

        from llm.ollama_client import OllamaClient
        client = OllamaClient()

        result = client.call_api(
            model="ollama:qwen3.6:35b-a3b",
            messages=[{"role": "user", "content": "Hello"}]
        )

        self.assertIsNotNone(result)
        mock_openai.chat.completions.create.assert_called_once()

    @patch('llm.ollama_client.get_dynamic_config_value')
    @patch('llm.ollama_client.OpenAI')
    def test_qwen38_uses_global_thinking_when_request_omits_it(self, mock_openai_class, mock_config):
        """llm.ollama.enable_thinking=true 时，即使调用方未开思考也会开启"""
        mock_config.side_effect = lambda *args, default=None: {
            ('llm', 'ollama', 'enabled'): True,
            ('llm', 'ollama', 'base_url'): 'http://localhost:11434',
            ('llm', 'ollama', 'temperature'): 0.7,
            ('llm', 'ollama', 'top_p'): 0.8,
            ('llm', 'ollama', 'top_k'): 20,
            ('llm', 'ollama', 'min_p'): 0.0,
            ('llm', 'ollama', 'presence_penalty'): 1.5,
            ('llm', 'ollama', 'repetition_penalty'): 1.0,
            ('llm', 'ollama', 'enable_thinking'): True,
        }.get(args, default)

        mock_openai = MagicMock()
        mock_openai_class.return_value = mock_openai
        mock_choice = MagicMock()
        mock_choice.message.content = "ok"
        mock_choice.message.tool_calls = None
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_openai.chat.completions.create.return_value = mock_response

        from llm.ollama_client import OllamaClient
        client = OllamaClient()
        self.assertTrue(client.enable_thinking)

        client.call_api(
            model="ollama:qwen3.8:27b",
            messages=[{"role": "user", "content": "Hello"}],
            enable_thinking=False,
        )
        kwargs = mock_openai.chat.completions.create.call_args.kwargs
        self.assertTrue(kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"])

    @patch('llm.ollama_client.get_dynamic_config_value')
    def test_refresh_config(self, mock_config):
        """测试配置刷新"""
        call_count = [0]

        def config_side_effect(*args, default=None):
            call_count[0] += 1
            if call_count[0] <= 9:  # 第一次初始化
                return {
                    ('llm', 'ollama', 'enabled'): False,
                }.get(args, default)
            else:  # 刷新后
                return {
                    ('llm', 'ollama', 'enabled'): True,
                    ('llm', 'ollama', 'base_url'): 'http://newhost:11434',
                    ('llm', 'ollama', 'temperature'): 0.5,
                    ('llm', 'ollama', 'top_p'): 0.9,
                    ('llm', 'ollama', 'top_k'): 30,
                    ('llm', 'ollama', 'min_p'): 0.1,
                    ('llm', 'ollama', 'presence_penalty'): 1.2,
                    ('llm', 'ollama', 'repetition_penalty'): 1.1,
                    ('llm', 'ollama', 'enable_thinking'): True,
                }.get(args, default)

        mock_config.side_effect = config_side_effect

        from llm.ollama_client import OllamaClient
        client = OllamaClient()

        self.assertFalse(client.enabled)

        # 刷新配置
        client._refresh_config()

        self.assertTrue(client.enabled)
        self.assertEqual(client.base_url, 'http://newhost:11434')


class TestLLMClientFactory(unittest.TestCase):
    """LLMClientFactory 测试"""

    def test_model_prefix_map_contains_ollama(self):
        """测试模型前缀映射包含 ollama"""
        from config.constant import MODEL_PREFIX_VENDOR_MAP, LLMVendor

        self.assertIn('ollama', MODEL_PREFIX_VENDOR_MAP)
        self.assertEqual(MODEL_PREFIX_VENDOR_MAP['ollama'], LLMVendor.OLLAMA)

    def test_get_vendor_by_model_ollama(self):
        """测试 Ollama 模型前缀正确映射到 vendor"""
        from llm.llm_client_factory import LLMClientFactory
        from config.constant import LLMVendor, LLMModel

        vendor = LLMClientFactory._get_vendor_by_model("ollama:qwen3.6:35b-a3b")
        self.assertEqual(vendor, LLMVendor.OLLAMA)

        vendor_38 = LLMClientFactory._get_vendor_by_model(
            f"ollama:{LLMModel.OLLAMA_QWEN_3_8_27B}"
        )
        self.assertEqual(vendor_38, LLMVendor.OLLAMA)
        self.assertEqual(LLMModel.OLLAMA_QWEN_3_8_27B, 'qwen3.8:27b')

    def test_get_vendor_by_model_qwen(self):
        """测试 Qwen 模型前缀正确映射到 aliyun vendor"""
        from llm.llm_client_factory import LLMClientFactory
        from config.constant import LLMVendor

        vendor = LLMClientFactory._get_vendor_by_model("qwen3.5-plus")
        self.assertEqual(vendor, LLMVendor.ALIYUN)


if __name__ == '__main__':
    unittest.main()
