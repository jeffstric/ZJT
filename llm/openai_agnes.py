"""
Agnes OpenAI 兼容格式 LLM 客户端
支持 agnes-2.5-flash / agnes-2.5-pro 对话模型（Chat Completions）

官方文档：https://www.agnes-ai.cn/zh-Hans/docs/overview
Base URL：https://api.agnes-ai.cn/v1
Thinking：extra_body.chat_template_kwargs.enable_thinking
"""
import logging
from .openai_base_client import OpenAIBaseClient
from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)


class AgnesOpenAIClient(OpenAIBaseClient):
    """Agnes OpenAI 兼容格式 LLM 客户端"""

    # model 表友好名称 -> 实际 API endpoint model ID 映射
    _MODEL_NAME_MAP = {
        'agnes-2.5-flash': 'agnes-2.5-flash',
        'agnes-2.5-pro': 'agnes-2.5-pro',
        # 兼容文档中的上一代 Flash
        'agnes-2.0-flash': 'agnes-2.0-flash',
    }

    def _refresh_config(self):
        """刷新 Agnes 配置"""
        self.api_key = get_dynamic_config_value('llm', 'agnes', 'api_key', default='')
        self.base_url = get_dynamic_config_value(
            'llm', 'agnes', 'base_url',
            default='https://api.agnes-ai.cn/v1'
        )
        self.vendor_name = 'agnes'
        # 使用自定义 _apply_thinking_params；thinking_mode 仅作日志标识
        self.thinking_mode = 'chat_template_kwargs'

        if self.api_key:
            logger.info(f"AgnesOpenAIClient config loaded: base_url={self.base_url}")
        else:
            logger.warning("AgnesOpenAIClient: API Key 未配置")

    def _resolve_model_name(self, model: str) -> str:
        """将 model 表中的友好名称映射为 Agnes 实际 API model ID"""
        actual = self._MODEL_NAME_MAP.get(model, model)
        if actual != model:
            logger.debug(f"AgnesOpenAIClient model mapping: {model} -> {actual}")
        return actual

    def _apply_thinking_params(self, kwargs, enable_thinking, thinking_effort):
        """Agnes Thinking 参数（OpenAI 兼容格式）

        官方要求：
        extra_body={"chat_template_kwargs": {"enable_thinking": true}}
        """
        kwargs.setdefault("extra_body", {})
        kwargs["extra_body"]["chat_template_kwargs"] = {
            "enable_thinking": bool(enable_thinking)
        }


_agnes_client = None


def get_agnes_openai_client() -> AgnesOpenAIClient:
    """获取 Agnes OpenAI 客户端单例"""
    global _agnes_client
    if _agnes_client is None:
        _agnes_client = AgnesOpenAIClient()
    else:
        _agnes_client._refresh_config()
    return _agnes_client
