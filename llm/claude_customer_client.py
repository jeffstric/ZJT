"""
Claude OpenAI 兼容格式 LLM 客户端
支持 claude-haiku-4-5 等 Claude 系列模型

配置参考（system_config 表或 config.yaml）：
  llm:claude:api_key   — API Key
  llm:claude:base_url  — API Base URL（默认 https://api.jiekou.ai/openai）
"""
import logging
from .openai_base_client import OpenAIBaseClient
from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)


class ClaudeCustomerClient(OpenAIBaseClient):
    """Claude OpenAI 兼容格式 LLM 客户端"""

    # model 表友好名称 -> 实际 API endpoint model ID 映射
    _MODEL_NAME_MAP = {
        'claude-haiku-4-5': 'claude-haiku-4-5-20251001',
    }

    def _refresh_config(self):
        """刷新 Claude 配置"""
        self.api_key = get_dynamic_config_value('llm', 'claude', 'api_key', default='')
        self.base_url = get_dynamic_config_value(
            'llm', 'claude', 'base_url',
            default='https://api.jiekou.ai/openai'
        )
        self.vendor_name = 'claude'
        self.thinking_mode = None

        if self.api_key:
            logger.info(f"ClaudeCustomerClient config loaded: base_url={self.base_url}")
        else:
            logger.warning("ClaudeCustomerClient: Claude API Key 未配置")

    def _resolve_model_name(self, model: str) -> str:
        """将 model 表中的友好名称映射为 Claude 实际 API model ID"""
        actual = self._MODEL_NAME_MAP.get(model, model)
        if actual != model:
            logger.debug(f"ClaudeCustomerClient model mapping: {model} -> {actual}")
        return actual


_claude_client = None


def get_claude_customer_client() -> ClaudeCustomerClient:
    """获取 Claude OpenAI 客户端单例"""
    global _claude_client
    if _claude_client is None:
        _claude_client = ClaudeCustomerClient()
    else:
        _claude_client._refresh_config()
    return _claude_client
