"""
VLLMClient 单元测试
"""
import unittest
from unittest.mock import patch, MagicMock


def _config_side_effect(overrides=None):
    """构造 llm.vllm.* 配置 mock（默认值对齐 Qwen3.8 官方思考模式）"""
    base = {
        ('llm', 'vllm', 'enabled'): True,
        ('llm', 'vllm', 'base_url'): 'http://localhost:8001',
        ('llm', 'vllm', 'temperature'): 1.0,
        ('llm', 'vllm', 'top_p'): 0.95,
        ('llm', 'vllm', 'top_k'): 20,
        ('llm', 'vllm', 'min_p'): 0.0,
        ('llm', 'vllm', 'presence_penalty'): 0.0,
        ('llm', 'vllm', 'repetition_penalty'): 1.0,
        ('llm', 'vllm', 'enable_thinking'): True,
    }
    if overrides:
        base.update(overrides)
    return lambda *args, default=None: base.get(args, default)


def _mock_openai_response(content="Test response", reasoning=None, cached=None):
    """构造 mock 的 OpenAI chat.completions 响应"""
    mock_openai = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_choice.message.tool_calls = None
    mock_choice.message.reasoning_content = reasoning
    mock_choice.finish_reason = "stop"

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 20
    mock_response.usage.total_tokens = 30
    mock_response.usage.prompt_tokens_details = None

    if cached is not None:
        details = MagicMock()
        details.cached_tokens = cached
        mock_response.usage.prompt_tokens_details = details

    mock_openai.chat.completions.create.return_value = mock_response
    return mock_openai


class TestVLLMClient(unittest.TestCase):
    """VLLMClient 测试"""

    @patch('llm.vllm_client.get_dynamic_config_value')
    def test_init_enabled_default_thinking_params(self, mock_config):
        """测试初始化：默认对齐 Qwen3.8 官方思考模式参数"""
        mock_config.side_effect = _config_side_effect()

        from llm.vllm_client import VLLMClient
        client = VLLMClient()

        self.assertTrue(client.enabled)
        self.assertEqual(client.base_url, 'http://localhost:8001')
        self.assertEqual(client.temperature, 1.0)
        self.assertEqual(client.top_p, 0.95)
        self.assertEqual(client.top_k, 20)
        self.assertEqual(client.min_p, 0.0)
        self.assertEqual(client.presence_penalty, 0.0)
        self.assertEqual(client.repetition_penalty, 1.0)
        self.assertTrue(client.enable_thinking)

    @patch('llm.vllm_client.get_dynamic_config_value')
    def test_init_disabled(self, mock_config):
        """测试初始化（禁用状态）"""
        mock_config.side_effect = _config_side_effect({('llm', 'vllm', 'enabled'): False})

        from llm.vllm_client import VLLMClient
        client = VLLMClient()

        self.assertFalse(client.enabled)

    @patch('llm.vllm_client.get_dynamic_config_value')
    def test_call_api_disabled(self, mock_config):
        """测试禁用时调用 API 抛出异常"""
        mock_config.side_effect = _config_side_effect({('llm', 'vllm', 'enabled'): False})

        from llm.vllm_client import VLLMClient
        client = VLLMClient()

        with self.assertRaises(Exception) as ctx:
            client.call_api(
                model="vllm:qwen3.8:27b",
                messages=[{"role": "user", "content": "test"}]
            )
        self.assertIn("vLLM 未启用", str(ctx.exception))

    @patch('llm.vllm_client.get_dynamic_config_value')
    @patch('llm.vllm_client.OpenAI')
    def test_call_api_success_strips_vllm_prefix(self, mock_openai_class, mock_config):
        """测试成功调用：剥离 vllm: 前缀、OpenAI 指向 base_url/v1"""
        mock_config.side_effect = _config_side_effect()
        mock_openai_class.return_value = _mock_openai_response()

        from llm.vllm_client import VLLMClient
        client = VLLMClient()

        result = client.call_api(
            model="vllm:qwen3.8:27b",
            messages=[{"role": "user", "content": "Hello"}]
        )

        self.assertIsNotNone(result)
        # OpenAI 客户端构造参数（含统一底层 HTTP 超时）
        from config.constant import ScriptSplitConstants
        mock_openai_class.assert_called_once_with(
            api_key="vllm",
            base_url="http://localhost:8001/v1",
            timeout=ScriptSplitConstants.LLM_HTTP_TIMEOUT_SECONDS,
        )
        # 请求体：模型名已剥离前缀
        kwargs = mock_openai_class.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "qwen3.8:27b")
        self.assertEqual(kwargs["temperature"], 1.0)
        self.assertEqual(kwargs["top_p"], 0.95)
        # vLLM 特有采样参数走 extra_body
        self.assertEqual(kwargs["extra_body"]["top_k"], 20)
        self.assertEqual(kwargs["extra_body"]["repetition_penalty"], 1.0)
        self.assertNotIn("min_p", kwargs["extra_body"])  # min_p=0 不传

    @patch('llm.vllm_client.get_dynamic_config_value')
    @patch('llm.vllm_client.OpenAI')
    def test_thinking_follows_global_when_not_passed(self, mock_openai_class, mock_config):
        """llm.vllm.enable_thinking=true 且调用方未传 enable_thinking 时开启思考"""
        mock_config.side_effect = _config_side_effect()
        mock_openai_class.return_value = _mock_openai_response()

        from llm.vllm_client import VLLMClient
        client = VLLMClient()
        self.assertTrue(client.enable_thinking)

        client.call_api(
            model="vllm:qwen3.8:27b",
            messages=[{"role": "user", "content": "Hello"}],
        )
        kwargs = mock_openai_class.return_value.chat.completions.create.call_args.kwargs
        self.assertTrue(kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"])

    @patch('llm.vllm_client.get_dynamic_config_value')
    @patch('llm.vllm_client.OpenAI')
    def test_thinking_explicit_false_overrides_global(self, mock_openai_class, mock_config):
        """全局 enable_thinking=true 时，调用方显式传 False 应能关闭思考"""
        mock_config.side_effect = _config_side_effect()
        mock_openai_class.return_value = _mock_openai_response()

        from llm.vllm_client import VLLMClient
        client = VLLMClient()
        self.assertTrue(client.enable_thinking)

        client.call_api(
            model="vllm:qwen3.8:27b",
            messages=[{"role": "user", "content": "Hello"}],
            enable_thinking=False,
        )
        kwargs = mock_openai_class.return_value.chat.completions.create.call_args.kwargs
        self.assertFalse(kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"])
        # 思考关闭时不下发 reasoning_effort
        self.assertNotIn("reasoning_effort", kwargs["extra_body"]["chat_template_kwargs"])

    @patch('llm.vllm_client.get_dynamic_config_value')
    @patch('llm.vllm_client.OpenAI')
    def test_thinking_effort_high_mapped_to_xhigh(self, mock_openai_class, mock_config):
        """思考开启时 thinking_effort=high 映射为 Qwen3.8 的 reasoning_effort=xhigh"""
        mock_config.side_effect = _config_side_effect()
        mock_openai_class.return_value = _mock_openai_response()

        from llm.vllm_client import VLLMClient
        client = VLLMClient()

        client.call_api(
            model="vllm:qwen3.8:27b",
            messages=[{"role": "user", "content": "Hello"}],
            thinking_effort="high",
        )
        kwargs = mock_openai_class.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["extra_body"]["chat_template_kwargs"]["reasoning_effort"], "xhigh")

    @patch('llm.vllm_client.get_dynamic_config_value')
    @patch('llm.vllm_client.OpenAI')
    def test_request_timeout_override(self, mock_openai_class, mock_config):
        """request_timeout 覆盖 client 默认 HTTP 超时（H3 链路场景）"""
        mock_config.side_effect = _config_side_effect()
        mock_openai_class.return_value = _mock_openai_response()

        from llm.vllm_client import VLLMClient
        client = VLLMClient()

        client.call_api(
            model="vllm:qwen3.8:27b",
            messages=[{"role": "user", "content": "Hello"}],
            request_timeout=90,
        )
        kwargs = mock_openai_class.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 90)

    @patch('llm.vllm_client.get_dynamic_config_value')
    @patch('llm.vllm_client.OpenAI')
    def test_thinking_disabled(self, mock_openai_class, mock_config):
        """llm.vllm.enable_thinking=false 且调用方未开时不下发思考"""
        mock_config.side_effect = _config_side_effect({('llm', 'vllm', 'enable_thinking'): False})
        mock_openai_class.return_value = _mock_openai_response()

        from llm.vllm_client import VLLMClient
        client = VLLMClient()

        client.call_api(
            model="vllm:qwen3.8:27b",
            messages=[{"role": "user", "content": "Hello"}],
        )
        kwargs = mock_openai_class.return_value.chat.completions.create.call_args.kwargs
        self.assertFalse(kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"])

    @patch('llm.vllm_client.get_dynamic_config_value')
    @patch('llm.vllm_client.OpenAI')
    def test_tools_passthrough(self, mock_openai_class, mock_config):
        """测试 tools 以 OpenAI function calling 格式透传"""
        mock_config.side_effect = _config_side_effect()
        mock_openai_class.return_value = _mock_openai_response()

        from llm.vllm_client import VLLMClient
        client = VLLMClient()

        tools = [{
            "type": "function",
            "function": {
                "name": "search",
                "description": "搜索",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}
            }
        }]
        client.call_api(
            model="vllm:qwen3.8:27b",
            messages=[{"role": "user", "content": "Hello"}],
            tools=tools,
        )
        kwargs = mock_openai_class.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["tools"], tools)

    @patch('llm.vllm_client.get_dynamic_config_value')
    @patch('llm.vllm_client.OpenAI')
    def test_reasoning_and_cached_tokens(self, mock_openai_class, mock_config):
        """测试思考内容与 prefix cache 命中量的提取"""
        mock_config.side_effect = _config_side_effect()
        mock_openai_class.return_value = _mock_openai_response(
            content="最终回复", reasoning="思考过程", cached=5
        )

        from llm.vllm_client import VLLMClient
        client = VLLMClient()

        result = client.call_api(
            model="vllm:qwen3.8:27b",
            messages=[{"role": "user", "content": "Hello"}]
        )
        message = result.choices[0].message
        self.assertEqual(message.content, "最终回复")
        self.assertEqual(message.reasoning_content, "思考过程")
        self.assertEqual(result.usage["input_token"], 10)
        self.assertEqual(result.usage["output_token"], 20)
        self.assertEqual(result.usage["total_token"], 30)
        self.assertEqual(result.usage["cache_read_token"], 5)

    @patch('llm.vllm_client.get_dynamic_config_value')
    def test_refresh_config(self, mock_config):
        """测试配置刷新"""
        call_count = [0]

        def config_side_effect(*args, default=None):
            call_count[0] += 1
            if call_count[0] <= 9:  # 第一次初始化
                return _config_side_effect({('llm', 'vllm', 'enabled'): False})(*args, default=default)
            else:  # 刷新后
                refreshed = {
                    ('llm', 'vllm', 'enabled'): True,
                    ('llm', 'vllm', 'base_url'): 'http://10.0.0.10:8001',
                    ('llm', 'vllm', 'temperature'): 0.8,
                    ('llm', 'vllm', 'top_p'): 0.9,
                    ('llm', 'vllm', 'top_k'): 30,
                    ('llm', 'vllm', 'min_p'): 0.1,
                    ('llm', 'vllm', 'presence_penalty'): 0.5,
                    ('llm', 'vllm', 'repetition_penalty'): 1.1,
                    ('llm', 'vllm', 'enable_thinking'): False,
                }
                return refreshed.get(args, default)

        mock_config.side_effect = config_side_effect

        from llm.vllm_client import VLLMClient
        client = VLLMClient()

        self.assertFalse(client.enabled)

        # 刷新配置
        client._refresh_config()

        self.assertTrue(client.enabled)
        self.assertEqual(client.base_url, 'http://10.0.0.10:8001')
        self.assertEqual(client.temperature, 0.8)


class TestVLLMClientFactory(unittest.TestCase):
    """LLMClientFactory 对 vllm 的路由测试"""

    def test_model_prefix_map_contains_vllm(self):
        """测试模型前缀映射包含 vllm"""
        from config.constant import MODEL_PREFIX_VENDOR_MAP, LLMVendor

        self.assertIn('vllm', MODEL_PREFIX_VENDOR_MAP)
        self.assertEqual(MODEL_PREFIX_VENDOR_MAP['vllm'], LLMVendor.VLLM)

    def test_get_vendor_by_model_vllm(self):
        """测试 vllm: 前缀模型路由到 VLLM vendor"""
        from llm.llm_client_factory import LLMClientFactory
        from config.constant import LLMVendor, LLMModel

        self.assertEqual(LLMModel.VLLM_QWEN_3_8_27B, 'qwen3.8:27b')
        vendor = LLMClientFactory._get_vendor_by_model(f"vllm:{LLMModel.VLLM_QWEN_3_8_27B}")
        self.assertEqual(vendor, LLMVendor.VLLM)

    @patch('llm.vllm_client.get_dynamic_config_value')
    def test_is_llm_client_configured_vllm_enabled(self, mock_config):
        """vLLM 本地客户端无需 api_key，启用时应判为已配置"""
        mock_config.side_effect = _config_side_effect()
        from llm.vllm_client import VLLMClient
        from llm.llm_client_factory import is_llm_client_configured

        client = VLLMClient()
        self.assertTrue(client.enabled)
        self.assertTrue(is_llm_client_configured(client))

    @patch('llm.vllm_client.get_dynamic_config_value')
    def test_is_llm_client_configured_vllm_disabled(self, mock_config):
        """vLLM 未启用（llm.vllm.enabled=false）时应判为未配置，
        使 H3 等回退链路继续选择下一个云端候选，而不是选中必败的本地模型"""
        mock_config.side_effect = _config_side_effect({('llm', 'vllm', 'enabled'): False})
        from llm.vllm_client import VLLMClient
        from llm.llm_client_factory import is_llm_client_configured

        client = VLLMClient()
        self.assertFalse(client.enabled)
        self.assertFalse(is_llm_client_configured(client))


if __name__ == '__main__':
    unittest.main()
