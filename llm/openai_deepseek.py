"""
DeepSeek OpenAI 兼容格式 LLM 客户端
支持 deepseek-v4-flash / deepseek-v4-pro 系列模型
官方 API 实际模型 ID 见 _MODEL_NAME_MAP（deepseek-v4-flash 系已下线，统一映射为 deepseek-flash）
"""
import logging
from .openai_base_client import OpenAIBaseClient
from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)


class DeepSeekOpenAIClient(OpenAIBaseClient):
    """DeepSeek OpenAI 兼容格式 LLM 客户端"""

    # model 表友好名称 -> 实际 API endpoint model ID 映射
    # 2026-09 官方公告：deepseek-v4-flash / deepseek-v4-flash-vision-exp 对应模型已下线，
    # 请求应由 DeepSeek-V4.1-Flash（model ID: deepseek-flash）提供服务；
    # deepseek-v4-pro 继续按原名提供调用服务。
    _MODEL_NAME_MAP = {
        'deepseek-v4-flash': 'deepseek-flash',
        'deepseek-v4-pro': 'deepseek-v4-pro',
        'deepseek-v4-flash-vision-exp': 'deepseek-flash',
        # 兼容即将弃用的旧模型名（映射为单级，不链式传递，需直接指向最终 API model ID）
        'deepseek-chat': 'deepseek-flash',
        'deepseek-reasoner': 'deepseek-v4-pro',
    }

    def _refresh_config(self):
        """刷新 DeepSeek 配置"""
        self.api_key = get_dynamic_config_value('llm', 'deepseek', 'api_key', default='')
        self.base_url = get_dynamic_config_value(
            'llm', 'deepseek', 'base_url',
            default='https://api.deepseek.com'
        )
        self.vendor_name = 'deepseek'
        self.thinking_mode = 'enable_thinking'

        if self.api_key:
            logger.info(f"DeepSeekOpenAIClient config loaded: base_url={self.base_url}")
        else:
            logger.warning("DeepSeekOpenAIClient: API Key 未配置")

    def _resolve_model_name(self, model: str) -> str:
        """将 model 表中的友好名称映射为 DeepSeek 实际 API model ID"""
        actual = self._MODEL_NAME_MAP.get(model, model)
        if actual != model:
            logger.debug(f"DeepSeekOpenAIClient model mapping: {model} -> {actual}")
        return actual

    def _apply_thinking_params(self, kwargs, enable_thinking, thinking_effort):
        """DeepSeek 专用 thinking 参数格式
        官方文档要求：extra_body={"thinking": {"type": "enabled"}}
        """
        kwargs.setdefault("extra_body", {})
        kwargs["extra_body"]["thinking"] = {
            "type": "enabled" if enable_thinking else "disabled"
        }
        if enable_thinking:
            kwargs["reasoning_effort"] = thinking_effort


_deepseek_client = None


def get_deepseek_openai_client() -> DeepSeekOpenAIClient:
    """获取 DeepSeek OpenAI 客户端单例"""
    global _deepseek_client
    if _deepseek_client is None:
        _deepseek_client = DeepSeekOpenAIClient()
    else:
        _deepseek_client._refresh_config()
    return _deepseek_client
