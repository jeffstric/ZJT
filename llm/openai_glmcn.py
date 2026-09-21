"""
智谱 BigModel 国内站（glmcn）OpenAI 兼容格式 LLM 客户端
支持 GLM-5.3 系列模型（API model ID 与 model 表友好名称一致，无需映射）
"""
import logging
from .openai_base_client import OpenAIBaseClient
from config.config_util import get_dynamic_config_value
from config.constant import LLMModel

logger = logging.getLogger(__name__)


class GlmcnOpenAIClient(OpenAIBaseClient):
    """智谱 BigModel 国内站 OpenAI 兼容格式 LLM 客户端

    GLM-5.3 始终启用思考（服务端无法关闭），reasoning_effort 仅支持
    low/high/max（无 "medium"），前端三档 low/medium/high 需经
    LLMModel.GLM_REASONING_EFFORT_MAP 映射，与火山方舟的 GLM-5.3 一致。
    """

    def _refresh_config(self):
        """刷新智谱 BigModel 配置"""
        self.api_key = get_dynamic_config_value('llm', 'glmcn', 'api_key', default='')
        self.base_url = get_dynamic_config_value(
            'llm', 'glmcn', 'base_url',
            default='https://open.bigmodel.cn/api/paas/v4'
        )
        self.vendor_name = 'glmcn'
        self.thinking_mode = 'reasoning_effort'

        if self.api_key:
            logger.info(f"GlmcnOpenAIClient config loaded: base_url={self.base_url}")
        else:
            logger.warning("GlmcnOpenAIClient: API Key 未配置")

    def _apply_thinking_params(self, kwargs, enable_thinking, thinking_effort):
        """GLM 思考强度映射。

        本供应商下全部模型均为 GLM 系列，无需按模型前缀区分；
        GLM-5.3 始终启用思考，关闭时不下发参数（服务端仍会计费思考，
        属模型固有行为，与火山方舟 GLM-5.3 一致）。
        """
        if not enable_thinking:
            return
        kwargs["reasoning_effort"] = LLMModel.GLM_REASONING_EFFORT_MAP.get(
            thinking_effort, thinking_effort
        )


_glmcn_client = None


def get_glmcn_openai_client() -> GlmcnOpenAIClient:
    """获取智谱 BigModel OpenAI 客户端单例"""
    global _glmcn_client
    if _glmcn_client is None:
        _glmcn_client = GlmcnOpenAIClient()
    else:
        _glmcn_client._refresh_config()
    return _glmcn_client
