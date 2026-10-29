"""
ZJT API OpenAI 兼容格式 LLM 客户端
支持 qwen3.5-plus、qwen3.6-plus 和 doubao 系列模型
"""
import logging
from .openai_base_client import OpenAIBaseClient
from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)


class ZJTOpenAIClient(OpenAIBaseClient):
    """ZJT API OpenAI 兼容格式 LLM 客户端"""

    # model 表友好名称 -> 实际 API endpoint model ID 映射
    # 260215 lite 快照已被方舟下线（2026-10-24 前后），同步改为 260428；
    # 本渠道 site_0 当前未配置 key，无法实测，启用前须先验证映射可用
    _MODEL_NAME_MAP = {
        'doubao-seed-2-0-pro': 'doubao-seed-2-0-pro-260215',
        'doubao-seed-2-0-lite': 'doubao-seed-2-0-lite-260428',
    }

    def _refresh_config(self):
        """刷新 ZJT API 配置"""
        self.api_key = get_dynamic_config_value('api_aggregator', 'site_0', 'api_key', default='')
        base_url = get_dynamic_config_value('api_aggregator', 'site_0', 'base_url', default='')

        # 确保 base_url 包含 /v1 路径
        if base_url:
            # 移除尾部斜杠
            base_url = base_url.rstrip('/')
            # 如果不以 /v1 结尾，添加 /v1
            if not base_url.endswith('/v1'):
                base_url = f"{base_url}/v1"

        self.base_url = base_url
        self.vendor_name = 'zjt_api'
        self.thinking_mode = None  # ZJT API 不支持 enable_thinking 参数透传

        if self.api_key:
            logger.info(f"ZJTOpenAIClient config loaded: base_url={self.base_url}")
        else:
            logger.warning("ZJTOpenAIClient: API Key 未配置 (api_aggregator.site_0.api_key)")

    def _resolve_model_name(self, model: str) -> str:
        """将 model 表中的友好名称映射为 ZJT API 实际 API model ID"""
        actual = self._MODEL_NAME_MAP.get(model, model)
        if actual != model:
            logger.debug(f"ZJTOpenAIClient model mapping: {model} -> {actual}")
        return actual


_zjt_client = None


def get_zjt_openai_client() -> ZJTOpenAIClient:
    """获取 ZJT API OpenAI 客户端单例"""
    global _zjt_client
    if _zjt_client is None:
        _zjt_client = ZJTOpenAIClient()
    else:
        _zjt_client._refresh_config()
    return _zjt_client
