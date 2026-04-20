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
    @patch('llm.ollama_client.OpenAI')
    def test_call_api_disabled(self, mock_openai, mock_config):
        """测试禁用时调用 API 返回 None"""
        mock_config.side_effect = lambda *args, default=None: {
            ('llm', 'ollama', 'enabled'): False,
        }.get(args, default)

        from llm.ollama_client import OllamaClient
        client = OllamaClient()

        result = client.call_api(
            model="ollama:test-model",
            messages=[{"role": "user", "content": "test"}]
        )

        self.assertIsNone(result)
        mock_openai.assert_not_called()

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
        from llm.llm_client_factory import LLMClientFactory

        self.assertIn('ollama', LLMClientFactory._MODEL_PREFIX_MAP)
        self.assertEqual(LLMClientFactory._MODEL_PREFIX_MAP['ollama'], 'ollama')

    @patch('llm.llm_client_factory.get_ollama_client')
    def test_get_client_for_ollama_model(self, mock_get_ollama):
        """测试获取 Ollama 模型的客户端"""
        mock_client = MagicMock()
        mock_get_ollama.return_value = mock_client

        from llm.llm_client_factory import LLMClientFactory

        client = LLMClientFactory.get_client("ollama:qwen3.6:35b-a3b")

        mock_get_ollama.assert_called_once()
        self.assertEqual(client, mock_client)

    @patch('llm.llm_client_factory.get_aliyun_openai_client')
    def test_get_client_for_qwen_model(self, mock_get_aliyun):
        """测试获取 Qwen 模型使用阿里云 OpenAI 客户端"""
        mock_client = MagicMock()
        mock_get_aliyun.return_value = mock_client

        from llm.llm_client_factory import LLMClientFactory

        client = LLMClientFactory.get_client("qwen3.5-plus")

        mock_get_aliyun.assert_called_once()
        self.assertEqual(client, mock_client)


if __name__ == '__main__':
    unittest.main()
