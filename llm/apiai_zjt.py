"""
ZJT API OpenAI 兼容格式 LLM 客户端
支持 qwen3.5-plus 和 qwen3.6-plus 模型
"""
import logging
from .openai_base_client import OpenAIBaseClient
from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)


class ZJTOpenAIClient(OpenAIBaseClient):
    """ZJT API OpenAI 兼容格式 LLM 客户端"""

    def _refresh_config(self):
        """刷新 ZJT API 配置"""
        self.api_key = get_dynamic_config_value('api_aggregator', 'site_0', 'api_key', default='')
        self.base_url = 'https://yunwu.ai/v1'
        self.vendor_name = 'zjt_api'
        self.thinking_mode = 'enable_thinking'  # ZJT API 支持 thinking 模式

        if self.api_key:
            logger.info(f"ZJTOpenAIClient config loaded: base_url={self.base_url}")
        else:
            logger.warning("ZJTOpenAIClient: API Key 未配置 (api_aggregator.site_0.api_key)")


_zjt_client = None


def get_zjt_openai_client() -> ZJTOpenAIClient:
    """获取 ZJT API OpenAI 客户端单例"""
    global _zjt_client
    if _zjt_client is None:
        _zjt_client = ZJTOpenAIClient()
    else:
        _zjt_client._refresh_config()
    return _zjt_client
