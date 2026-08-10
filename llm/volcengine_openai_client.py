"""
火山引擎 / Doubao OpenAI 兼容格式 LLM 客户端
支持 doubao 系列模型，以及方舟上的 DeepSeek-V4 系列
"""
import logging
from .openai_base_client import OpenAIBaseClient
from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)


class VolcengineOpenAIClient(OpenAIBaseClient):
    """火山引擎（Doubao / DeepSeek）OpenAI 兼容格式 LLM 客户端"""

    # model 表友好名称 -> 实际 API endpoint model ID 映射
    # DeepSeek 在方舟控制台展示为 DeepSeek-V4-flash / DeepSeek-V4-pro，
    # 兼容 API 使用 deepseek-v4-flash / deepseek-v4-pro 模型名（可与接入点 ID 混用）。
    _MODEL_NAME_MAP = {
        'doubao-seed-2-0-pro': 'doubao-seed-2-0-pro-260215',
        'doubao-seed-2-0-lite': 'doubao-seed-2-0-lite-260215',
        'deepseek-v4-flash': 'deepseek-v4-flash',
        'deepseek-v4-pro': 'deepseek-v4-pro',
    }

    def _refresh_config(self):
        """刷新火山引擎配置"""
        self.api_key = get_dynamic_config_value('volcengine', 'api_key', default='')
        self.base_url = get_dynamic_config_value(
            'volcengine', 'base_url',
            default='https://ark.cn-beijing.volces.com/api/v3'
        )
        self.vendor_name = 'volcengine'
        self.thinking_mode = 'reasoning_effort'

        if self.api_key:
            logger.info(f"VolcengineOpenAIClient config loaded: base_url={self.base_url}")
        else:
            logger.warning("VolcengineOpenAIClient: API Key 未配置")

    def _resolve_model_name(self, model: str) -> str:
        """将 model 表中的友好名称映射为火山引擎实际 API model ID"""
        actual = self._MODEL_NAME_MAP.get(model, model)
        if actual != model:
            logger.debug(f"VolcengineOpenAIClient model mapping: {model} -> {actual}")
        return actual


_volcengine_client = None


def get_volcengine_openai_client() -> VolcengineOpenAIClient:
    """获取火山引擎 OpenAI 客户端单例"""
    global _volcengine_client
    if _volcengine_client is None:
        _volcengine_client = VolcengineOpenAIClient()
    else:
        _volcengine_client._refresh_config()
    return _volcengine_client
