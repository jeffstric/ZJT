"""
OpenAI 兼容格式 LLM 客户端基类
封装通用的 OpenAI API 调用逻辑，供各供应商子类继承

子类只需实现 _refresh_config() 加载自身配置即可。
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
    """获取 LLM 日志记录器（与 gemini_client 共享）"""
    from .gemini_client import llm_logger
    return llm_logger


def _mask_api_key(api_key: str) -> str:
    """对 API 密钥进行掩码处理"""
    if not api_key or len(api_key) < 8:
        return "***"
    return f"{api_key[:4]}...{api_key[-4:]}"


class OpenAIBaseClient(BaseLLMClient):
    """OpenAI 兼容格式 LLM 客户端基类

    子类只需实现 _refresh_config() 设置以下属性：
    - api_key: str
    - base_url: str
    - vendor_name: str
    - thinking_mode: str | None  ('enable_thinking' | 'reasoning_effort' | None)
    """

    def __init__(self):
        self.api_key: str = ''
        self.base_url: str = ''
        self.vendor_name: str = ''
        self.thinking_mode: Optional[str] = None
        self._refresh_config()

    def _refresh_config(self):
        """刷新配置（子类必须实现）"""
        raise NotImplementedError("子类必须实现 _refresh_config()")

    def _resolve_model_name(self, model: str) -> str:
        """将 model 表中的友好名称解析为实际 API model ID（子类可重写）"""
        return model

    def _build_openai_client(self) -> OpenAI:
        """构建并返回 openai.OpenAI 实例"""
        return OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _apply_thinking_params(self, kwargs: Dict[str, Any], enable_thinking: bool, thinking_effort: str):
        """按供应商规则注入思考模式参数"""
        if not enable_thinking or not self.thinking_mode:
            return

        if self.thinking_mode == 'reasoning_effort':
            kwargs["reasoning_effort"] = thinking_effort
        elif self.thinking_mode == 'enable_thinking':
            kwargs.setdefault("extra_body", {})
            kwargs["extra_body"]["enable_thinking"] = True

    def _extract_usage(self, completion: Any) -> Dict[str, int]:
        """从 completion 响应中提取 token 使用量"""
        usage_info = {
            "input_token": 0,
            "output_token": 0,
            "total_token": 0,
            "cache_read_token": 0
        }

        if not hasattr(completion, 'usage') or not completion.usage:
            return usage_info

        usage = completion.usage
        usage_info["input_token"] = getattr(usage, 'prompt_tokens', 0) or 0
        usage_info["output_token"] = getattr(usage, 'completion_tokens', 0) or 0
        usage_info["total_token"] = getattr(usage, 'total_tokens', 0) or 0

        if hasattr(usage, 'prompt_tokens_details') and usage.prompt_tokens_details:
            if hasattr(usage.prompt_tokens_details, 'cached_tokens'):
                usage_info["cache_read_token"] = usage.prompt_tokens_details.cached_tokens or 0

        return usage_info

    def call_api(
        self,
        model: str,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 65536,
        auth_token: str = None,
        vendor_id: int = None,
        model_id: int = None,
        enable_thinking: bool = False,
        thinking_effort: str = "medium"
    ) -> Any:
        """
        调用 OpenAI 兼容格式 API

        Args:
            model: 模型名称
            messages: OpenAI 格式的消息列表
            tools: 工具定义列表（OpenAI function calling 格式）
            temperature: 温度参数
            max_tokens: 最大输出 token 数
            enable_thinking: 是否开启思考模式
            thinking_effort: 思考强度（值：low/medium/high）

        Returns:
            Response 对象
        """
        if not self.api_key:
            raise Exception(f"供应商 {self.vendor_name} 的 API Key 未配置")

        try:
            client = self._build_openai_client()
            actual_model = self._resolve_model_name(model)

            kwargs = {
                "model": actual_model,
                "messages": messages,
                "temperature": temperature,
            }

            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            self._apply_thinking_params(kwargs, enable_thinking, thinking_effort)

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
            llm_logger.info("=" * 80)
            llm_logger.info(f"{self.vendor_name.upper()} API REQUEST:")
            llm_logger.info(f"  Model: {actual_model}")
            llm_logger.info(f"  Base URL: {self.base_url}")
            llm_logger.info(f"  API Key: {_mask_api_key(self.api_key)}")
            llm_logger.info(f"  Messages count: {len(messages)}")
            llm_logger.info(f"  Temperature: {temperature}")
            llm_logger.info(f"  Max tokens: {max_tokens}")
            llm_logger.info(f"  Thinking: enabled={enable_thinking}, mode={self.thinking_mode}, effort={thinking_effort}")
            if tools:
                llm_logger.info(f"  Tools count: {len(tools)}")

            # 脱敏后打印完整请求 payload
            safe_kwargs = json.loads(json.dumps(kwargs, ensure_ascii=False, default=str))
            if "messages" in safe_kwargs:
                for msg in safe_kwargs["messages"]:
                    if "content" in msg and isinstance(msg["content"], str) and len(msg["content"]) > 200:
                        msg["content"] = msg["content"][:200] + "... [truncated]"
            payload_str = json.dumps(safe_kwargs, ensure_ascii=False, indent=2)
            llm_logger.info(f"{self.vendor_name.upper()} API request payload:\n{payload_str}")

            logger.info(f"{self.vendor_name} API request: model={actual_model}, messages_count={len(messages)}")

            completion = client.chat.completions.create(**kwargs)

            choice = completion.choices[0]
            message = choice.message

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
            usage_info = self._extract_usage(completion)

            logger.info(f"{self.vendor_name} API response: content_length={len(content)}, tool_calls={len(tool_calls) if tool_calls else 0}")

            llm_logger.info("=" * 80)
            llm_logger.info(f"{self.vendor_name.upper()} API RESPONSE:")
            llm_logger.info(f"  Content length: {len(content)} chars")
            if content:
                llm_logger.info(f"  Content:\n{content}")
            if tool_calls:
                llm_logger.info(f"  Tool calls count: {len(tool_calls)}")
                for i, tc in enumerate(tool_calls):
                    llm_logger.info(f"    Tool[{i}]: {tc.function.name}")
                    llm_logger.info(f"      Args: {tc.function.arguments}")
            llm_logger.info(f"  Token usage: {usage_info}")
            llm_logger.info("-" * 80)

            if auth_token and model_id:
                self._log_token_usage(usage_info, auth_token, vendor_id, model_id)

            return self._create_response(content, tool_calls, usage_info)

        except Exception as e:
            logger.error(f"{self.vendor_name} API call failed: {e}")
            raise
