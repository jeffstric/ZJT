"""
LLM 客户端基类
定义统一的接口，供 Gemini、OpenAI 等具体 driver 实现
"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from perseids_server.client import make_perseids_request

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """LLM 客户端抽象基类"""

    # 响应格式类 - 所有 driver 返回统一格式
    class Message:
        def __init__(self, content: str, tool_calls: Optional[List] = None, thought_signature: Optional[str] = None, reasoning_content: Optional[str] = None):
            self.content = content
            self.tool_calls = tool_calls
            self.thought_signature = thought_signature
            self.reasoning_content = reasoning_content

    class Choice:
        def __init__(self, message: 'BaseLLMClient.Message', finish_reason: Optional[str] = None):
            self.message = message
            # 归一化后的完成原因（小写下划线），如 stop / length / tool_calls / content_filter
            self.finish_reason = BaseLLMClient.normalize_finish_reason(finish_reason)

        @property
        def is_truncated(self) -> bool:
            """是否因输出上限被截断（finish_reason == 'length'）"""
            return self.finish_reason == "length"

    class Response:
        def __init__(self, choices: List['BaseLLMClient.Choice'], usage: Optional[Dict] = None):
            self.choices = choices
            self.usage = usage or {}

    @staticmethod
    def normalize_finish_reason(raw: Optional[str]) -> Optional[str]:
        """将各 provider 的 finish_reason 归一化为小写下划线风格。

        - OpenAI / Ollama / OpenAI 兼容：stop / length / tool_calls / content_filter
        - Gemini：STOP / MAX_TOKENS / SAFETY 等（驼峰 key，值全大写）
        归一化后 engine 只需判断 == 'length'，无需关心 provider 差异。
        """
        if not raw:
            return None
        value = str(raw).strip().lower()
        # Gemini MAX_TOKENS 映射为 OpenAI 风格的 length
        if value in ("max_tokens",):
            return "length"
        return value

    @abstractmethod
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
        thinking_effort: str = "medium",
        agent_id: Optional[str] = None,
        agent_scope: Optional[str] = None,
        request_timeout: Optional[float] = None,
        suppress_payload_logging: bool = False,
    ) -> Any:
        """
        调用 LLM API

        Args:
            model: 模型名称
            messages: OpenAI 格式的消息列表
            tools: 工具定义列表
            temperature: 温度参数
            max_tokens: 最大输出 token 数
            auth_token: 认证 token（用于记录用量）
            vendor_id: 供应商 ID
            model_id: 模型 ID
            enable_thinking: 是否开启思考模式
            thinking_effort: 思考强度（doubao 用，值：low/medium/high）
            request_timeout: 单次请求 HTTP 超时（秒），None 时用各客户端默认值
            suppress_payload_logging: 是否禁止记录请求、响应和异常正文

        Returns:
            Response 对象（包含 choices 和 usage）
        """
        pass

    def _log_request_context(self, llm_logger: logging.Logger, agent_id: Optional[str] = None, agent_scope: Optional[str] = None):
        """记录 Agent 请求上下文信息（公共日志逻辑）"""
        if agent_id:
            llm_logger.info(f"  Agent: {agent_id}")
        if agent_scope:
            llm_logger.info(f"  Agent scope: {agent_scope}")

    def _create_response(self, content: str, tool_calls: Optional[List] = None, usage: Optional[Dict] = None, reasoning_content: Optional[str] = None, finish_reason: Optional[str] = None) -> 'Response':
        """创建标准响应格式"""
        message = self.Message(content, tool_calls, reasoning_content=reasoning_content)
        return self.Response([self.Choice(message, finish_reason)], usage)

    def _log_token_usage(
        self,
        usage: Dict,
        auth_token: str,
        vendor_id: int,
        model_id: int,
        *,
        suppress_error_details: bool = False,
    ):
        """记录 token 使用量到 perseids"""
        try:
            input_token = usage.get("input_token", 0)
            output_token = usage.get("output_token", 0)
            total_token = usage.get("total_token", 0)

            headers = {'Authorization': f'Bearer {auth_token}'}
            success, log_message, response_data = make_perseids_request(
                endpoint='user/token_log',
                method='POST',
                headers=headers,
                data={
                    # ⚠️ input_token 使用 total_token - output_token 而非原始 input_token
                    # 因为部分供应商的 total_token 包含 cache_read，而 input_token 不含
                    # 用差值可确保 input + output = total 的一致性
                    "input_token": total_token - output_token,
                    "output_token": output_token,
                    "cache_creation": 0,
                    "cache_read": usage.get("cache_read_token", 0),
                    "raw_input_token": input_token,
                    "model_id": model_id,
                    "vendor_id": vendor_id
                }
            )

            if not success:
                if suppress_error_details:
                    logger.info("增加 token 日志失败")
                else:
                    logger.info(f"增加 token 日志失败: {log_message}")
        except Exception as e:
            if suppress_error_details:
                logger.warning(
                    "记录 token 使用量失败: error_type=%s",
                    type(e).__name__,
                )
            else:
                logger.warning(f"记录 token 使用量失败: {e}")
