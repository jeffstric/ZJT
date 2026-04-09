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
        def __init__(self, content: str, tool_calls: Optional[List] = None, thought_signature: Optional[str] = None):
            self.content = content
            self.tool_calls = tool_calls
            self.thought_signature = thought_signature

    class Choice:
        def __init__(self, message: 'BaseLLMClient.Message'):
            self.message = message

    class Response:
        def __init__(self, choices: List['BaseLLMClient.Choice'], usage: Optional[Dict] = None):
            self.choices = choices
            self.usage = usage or {}

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
        model_id: int = None
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

        Returns:
            Response 对象（包含 choices 和 usage）
        """
        pass

    def _create_response(self, content: str, tool_calls: Optional[List] = None, usage: Optional[Dict] = None) -> 'Response':
        """创建标准响应格式"""
        message = self.Message(content, tool_calls)
        return self.Response([self.Choice(message)], usage)

    def _log_token_usage(self, usage: Dict, auth_token: str, vendor_id: int, model_id: int):
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
                logger.info(f"增加 token 日志失败: {log_message}")
        except Exception as e:
            logger.warning(f"记录 token 使用量失败: {e}")
