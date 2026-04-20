"""
Ollama 本地模型 LLM 客户端
使用 Ollama 的 OpenAI 兼容端点 /v1/chat/completions
"""
import json
import logging
from typing import Dict, List, Any, Optional
from openai import OpenAI
from config.config_util import get_dynamic_config_value
from .base_llm_client import BaseLLMClient
from script_writer_core.log_utils import should_log_debug

logger = logging.getLogger(__name__)


def _get_llm_logger():
    """获取 LLM 日志记录器"""
    from .gemini_client import llm_logger
    return llm_logger


class OllamaClient(BaseLLMClient):
    """Ollama 本地模型 LLM 客户端"""

    def __init__(self):
        """初始化 Ollama 客户端"""
        self._refresh_config()

    def _refresh_config(self):
        """刷新配置（从数据库动态读取）"""
        self.enabled = get_dynamic_config_value('llm', 'ollama', 'enabled', default=False)
        self.base_url = get_dynamic_config_value('llm', 'ollama', 'base_url', default='http://localhost:11434')
        # 模型参数配置
        self.temperature = get_dynamic_config_value('llm', 'ollama', 'temperature', default=0.7)
        self.top_p = get_dynamic_config_value('llm', 'ollama', 'top_p', default=0.8)
        self.top_k = get_dynamic_config_value('llm', 'ollama', 'top_k', default=20)
        self.min_p = get_dynamic_config_value('llm', 'ollama', 'min_p', default=0.0)
        self.presence_penalty = get_dynamic_config_value('llm', 'ollama', 'presence_penalty', default=1.5)
        self.repetition_penalty = get_dynamic_config_value('llm', 'ollama', 'repetition_penalty', default=1.0)
        self.enable_thinking = get_dynamic_config_value('llm', 'ollama', 'enable_thinking', default=False)

        if self.enabled:
            logger.info(f"OllamaClient config loaded: base_url={self.base_url}, temp={self.temperature}, top_p={self.top_p}")
        else:
            logger.debug("Ollama is disabled")

    def call_api(
        self,
        model: str,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 64000,
        auth_token: str = None,
        vendor_id: int = None,
        model_id: int = None
    ) -> Any:
        """
        调用 Ollama 本地模型 API

        Args:
            model: 模型名称（如 ollama:qwen2.5:7b）
            messages: OpenAI 格式的消息列表
            tools: 工具定义列表（OpenAI function calling 格式）
            temperature: 温度参数
            max_tokens: 最大输出 token 数
            auth_token: 认证 token（本地模型不需要）
            vendor_id: 供应商 ID
            model_id: 模型 ID

        Returns:
            Response 对象
        """
        if not self.enabled:
            raise Exception("Ollama 未启用，请在配置中设置 llm.ollama.enabled = true")

        # 处理模型名称：移除 "ollama:" 前缀
        actual_model = model
        if model.lower().startswith("ollama:"):
            actual_model = model[7:]  # 移除 "ollama:" 前缀

        try:
            # 使用 Ollama 的 OpenAI 兼容端点
            client = OpenAI(
                api_key="ollama",  # Ollama 不需要真正的 API key，但 OpenAI 库需要一个值
                base_url=f"{self.base_url}/v1",
            )

            # 使用配置的参数，调用方传入的 temperature 仅作为 fallback
            actual_temperature = self.temperature if self.temperature is not None else temperature

            kwargs = {
                "model": actual_model,
                "messages": messages,
                "temperature": actual_temperature,
                "top_p": self.top_p,
                "presence_penalty": self.presence_penalty,
                "frequency_penalty": self.repetition_penalty,  # OpenAI API 使用 frequency_penalty
            }

            # Ollama 特有参数通过 extra_body 传递
            extra_body = {}
            if self.top_k is not None and self.top_k > 0:
                extra_body["top_k"] = self.top_k
            if self.min_p is not None and self.min_p > 0:
                extra_body["min_p"] = self.min_p
            # 思维链配置
            extra_body["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}
            if extra_body:
                kwargs["extra_body"] = extra_body

            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            # 如果有 tools，添加 function calling 支持
            if tools:
                functions = []
                for tool in tools:
                    if tool.get("type") == "function":
                        func = tool["function"]
                        functions.append({
                            "name": func["name"],
                            "description": func.get("description", ""),
                            "parameters": func.get("parameters", {})
                        })
                if functions:
                    kwargs["tools"] = [{"type": "function", "function": f} for f in functions]

            llm_logger = _get_llm_logger()
            llm_logger.info("="*80)
            llm_logger.info(f"OLLAMA API REQUEST:")
            llm_logger.info(f"  Model: {actual_model}")
            llm_logger.info(f"  Base URL: {self.base_url}")
            llm_logger.info(f"  Messages count: {len(messages)}")
            llm_logger.info(f"  Temperature: {actual_temperature}, top_p: {self.top_p}, top_k: {self.top_k}")
            llm_logger.info(f"  presence_penalty: {self.presence_penalty}, repetition_penalty: {self.repetition_penalty}")
            llm_logger.info(f"  enable_thinking: {self.enable_thinking}")
            llm_logger.info(f"  Max tokens: {max_tokens}")
            if tools:
                llm_logger.info(f"  Tools count: {len(tools)}")

            if should_log_debug():
                payload_str = json.dumps(kwargs, ensure_ascii=False, indent=2, default=str)
                llm_logger.debug(f"Ollama API request payload:\n{payload_str}")

            logger.info(f"Ollama API request: model={actual_model}, messages_count={len(messages)}")

            completion = client.chat.completions.create(**kwargs)

            # 提取响应内容
            choice = completion.choices[0]
            message = choice.message

            # 处理 tool_calls
            tool_calls = None
            if hasattr(message, 'tool_calls') and message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    tool_call = type('obj', (object,), {
                        'id': tc.id,
                        'type': 'function',
                        'function': type('obj', (object,), {
                            'name': tc.function.name,
                            'arguments': tc.function.arguments
                        })()
                    })()
                    tool_calls.append(tool_call)

            content = message.content or ""

            # 提取 token 使用量（Ollama 可能不返回完整的 usage 信息）
            usage_info = {}
            if hasattr(completion, 'usage') and completion.usage:
                usage_info = {
                    "input_token": getattr(completion.usage, 'prompt_tokens', 0) or 0,
                    "output_token": getattr(completion.usage, 'completion_tokens', 0) or 0,
                    "total_token": getattr(completion.usage, 'total_tokens', 0) or 0,
                    "cache_read_token": 0
                }

            logger.info(f"Ollama API response: content_length={len(content)}, tool_calls={len(tool_calls) if tool_calls else 0}")

            llm_logger.info("="*80)
            llm_logger.info("OLLAMA API RESPONSE:")
            llm_logger.info(f"  Content length: {len(content)} chars")
            if content:
                llm_logger.info(f"  Content:\n{content}")
            if tool_calls:
                llm_logger.info(f"  Tool calls count: {len(tool_calls)}")
                for i, tc in enumerate(tool_calls):
                    llm_logger.info(f"    Tool[{i}]: {tc.function.name}")
                    llm_logger.info(f"      Args: {tc.function.arguments}")
            llm_logger.info(f"  Token usage: {usage_info}")
            llm_logger.info("-"*80)

            # 记录 token 使用情况（即使是本地模型，也记录统计数据用于分析）
            if auth_token and model_id:
                self._log_token_usage(usage_info, auth_token, vendor_id, model_id)

            return self._create_response(content, tool_calls, usage_info)

        except Exception as e:
            logger.error(f"Ollama API call failed: {e}")
            raise


# 全局单例
_ollama_client = None


def get_ollama_client() -> OllamaClient:
    """获取 Ollama 客户端单例（每次调用时刷新配置）"""
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    else:
        _ollama_client._refresh_config()
    return _ollama_client
