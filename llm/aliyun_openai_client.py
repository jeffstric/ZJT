"""
阿里云 / 百炼 OpenAI 兼容格式 LLM 客户端
支持 qwen 系列模型
"""
import logging
from .openai_base_client import OpenAIBaseClient
from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)


class AliyunOpenAIClient(OpenAIBaseClient):
    """阿里云（百炼）OpenAI 兼容格式 LLM 客户端"""

    def _refresh_config(self):
        """刷新阿里云配置"""
        self.api_key = get_dynamic_config_value('llm', 'qwen', 'api_key', default='')
        self.base_url = get_dynamic_config_value(
            'llm', 'qwen', 'base_url',
            default='https://dashscope.aliyuncs.com/compatible-mode/v1'
        )
        self.vendor_name = 'aliyun'
        self.thinking_mode = 'enable_thinking'

        if self.api_key:
            logger.info(f"AliyunOpenAIClient config loaded: base_url={self.base_url}")
        else:
            logger.warning("AliyunOpenAIClient: Qwen API Key 未配置")


_aliyun_client = None


def get_aliyun_openai_client() -> AliyunOpenAIClient:
    """获取阿里云 OpenAI 客户端单例"""
    global _aliyun_client
    if _aliyun_client is None:
        _aliyun_client = AliyunOpenAIClient()
    else:
        _aliyun_client._refresh_config()
    return _aliyun_client
