"""
OpenAI 兼容格式 LLM 客户端
支持 Qwen、OpenAI 等使用 OpenAI API 格式的模型
"""
import json
import logging
from typing import Dict, List, Any, Optional
from openai import OpenAI
from config.config_util import get_dynamic_config_value
from .base_llm_client import BaseLLMClient
from script_writer_core.log_utils import should_log_debug

logger = logging.getLogger(__name__)

# 获取 LLM 日志记录器（与 gemini_client 共享）
def _get_llm_logger():
    from .gemini_client import llm_logger
    return llm_logger

def _mask_api_key(api_key: str) -> str:
    """对 API 密钥进行掩码处理"""
    if not api_key or len(api_key) < 8:
        return "***"
    return f"{api_key[:4]}...{api_key[-4:]}"

class OpenAIClient(BaseLLMClient):
    """OpenAI 兼容格式 LLM 客户端"""

    def __init__(self):
        """初始化 OpenAI 客户端"""
        self._refresh_config()

    def _refresh_config(self):
        """刷新配置（从数据库动态读取）"""
        # Qwen 配置
        self.api_key = get_dynamic_config_value('llm', 'qwen', 'api_key', default='')
        self.base_url = get_dynamic_config_value('llm', 'qwen', 'base_url', default='https://dashscope.aliyuncs.com/compatible-mode/v1')

        if not self.api_key:
            logger.warning("Qwen API Key 未配置")
        else:
            logger.info(f"OpenAIClient config loaded: base_url={self.base_url}")

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
        调用 OpenAI 兼容格式 API

        Args:
            model: 模型名称（如 qwen3.5-plus, qwen3.6-plus, gpt-4o）
            messages: OpenAI 格式的消息列表
            tools: 工具定义列表（OpenAI function calling 格式）
            temperature: 温度参数
            max_tokens: 最大输出 token 数

        Returns:
            Response 对象
        """
        if not self.api_key:
            raise Exception("API Key 未配置")

        try:
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )

            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }

            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            # 如果有 tools，添加 function calling 支持
            if tools:
                # 转换为 OpenAI function calling 格式
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
            llm_logger.info(f"OPENAI API REQUEST:")
            llm_logger.info(f"  Model: {model}")
            llm_logger.info(f"  Base URL: {self.base_url}")
            llm_logger.info(f"  API Key: {_mask_api_key(self.api_key)}")
            llm_logger.info(f"  Messages count: {len(messages)}")
            llm_logger.info(f"  Temperature: {temperature}")
            llm_logger.info(f"  Max tokens: {max_tokens}")
            if tools:
                llm_logger.info(f"  Tools count: {len(tools)}")

            if should_log_debug():
                payload_str = json.dumps(kwargs, ensure_ascii=False, indent=2, default=str)
                llm_logger.debug(f"OpenAI API request payload:\n{payload_str}")

            logger.info(f"OpenAI API request: model={model}, messages_count={len(messages)}")

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

            # 提取 token 使用量
            usage_info = {}
            if hasattr(completion, 'usage') and completion.usage:
                usage_info = {
                    "input_token": completion.usage.prompt_tokens or 0,
                    "output_token": completion.usage.completion_tokens or 0,
                    "total_token": completion.usage.total_tokens or 0,
                    "cache_read_token": 0
                }
                # Qwen/OpenAI: prompt_tokens_details.cached_tokens
                if hasattr(completion.usage, 'prompt_tokens_details') and completion.usage.prompt_tokens_details:
                    if hasattr(completion.usage.prompt_tokens_details, 'cached_tokens'):
                        usage_info["cache_read_token"] = completion.usage.prompt_tokens_details.cached_tokens or 0

            logger.info(f"OpenAI API response: content_length={len(content)}, tool_calls={len(tool_calls) if tool_calls else 0}")

            llm_logger.info("="*80)
            llm_logger.info("OPENAI API RESPONSE:")
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

            # 记录 token 使用到 perseids
            if auth_token and model_id:
                self._log_token_usage(usage_info, auth_token, vendor_id, model_id)

            return self._create_response(content, tool_calls, usage_info)

        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            raise


# 全局单例
_openai_client = None


def get_openai_client() -> OpenAIClient:
    """获取 OpenAI 客户端单例（每次调用时刷新配置）"""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAIClient()
    else:
        _openai_client._refresh_config()
    return _openai_client
