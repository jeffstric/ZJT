"""
小米 MiMo OpenAI 兼容格式 LLM 客户端
支持 mimo-v2.5 / mimo-v2.5-pro 系列模型
接入方式为 Token Plan 套餐（包月 credits），调用协议与按量 API 一致：
OpenAI 兼容端点 https://token-plan-cn.xiaomimimo.com/v1
"""
import logging
from .openai_base_client import OpenAIBaseClient
from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)


class MimoOpenAIClient(OpenAIBaseClient):
    """小米 MiMo OpenAI 兼容格式 LLM 客户端"""

    # model 表友好名称 -> 实际 API endpoint model ID 映射
    _MODEL_NAME_MAP = {
        'mimo-v2.5': 'mimo-v2.5',
        'mimo-v2.5-pro': 'mimo-v2.5-pro',
    }

    def _refresh_config(self):
        """刷新小米 MiMo 配置"""
        self.api_key = get_dynamic_config_value('llm', 'mimo', 'api_key', default='')
        self.base_url = get_dynamic_config_value(
            'llm', 'mimo', 'base_url',
            default='https://token-plan-cn.xiaomimimo.com/v1'
        )
        self.vendor_name = 'mimo'
        self.thinking_mode = 'enable_thinking'

        if self.api_key:
            logger.info(f"MimoOpenAIClient config loaded: base_url={self.base_url}")
        else:
            logger.warning("MimoOpenAIClient: API Key 未配置")

    def _resolve_model_name(self, model: str) -> str:
        """将 model 表中的友好名称映射为 MiMo 实际 API model ID"""
        actual = self._MODEL_NAME_MAP.get(model, model)
        if actual != model:
            logger.debug(f"MimoOpenAIClient model mapping: {model} -> {actual}")
        return actual

    def _apply_thinking_params(self, kwargs, enable_thinking, thinking_effort):
        """小米 MiMo 专用 thinking 参数格式
        官方文档要求：extra_body={"thinking": {"type": "enabled"}}
        """
        kwargs.setdefault("extra_body", {})
        kwargs["extra_body"]["thinking"] = {
            "type": "enabled" if enable_thinking else "disabled"
        }
        if enable_thinking:
            kwargs["reasoning_effort"] = thinking_effort


_mimo_client = None


def get_mimo_openai_client() -> MimoOpenAIClient:
    """获取小米 MiMo OpenAI 客户端单例"""
    global _mimo_client
    if _mimo_client is None:
        _mimo_client = MimoOpenAIClient()
    else:
        _mimo_client._refresh_config()
    return _mimo_client
