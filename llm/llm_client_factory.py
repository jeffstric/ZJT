"""
LLM 客户端工厂类
根据模型类型自动选择对应的 driver（Gemini、AliyunOpenAI、VolcengineOpenAI、Ollama）

映射关系：
  模型前缀 → vendor（config/constant.py 中 MODEL_PREFIX_VENDOR_MAP 定义）
  vendor → client getter（本文件 _VENDOR_CLIENT_MAP 定义）
"""
import logging
from typing import Optional

from config.constant import LLMVendor, MODEL_PREFIX_VENDOR_MAP
from .base_llm_client import BaseLLMClient
from .gemini_client import GeminiClient, get_gemini_client
from .ollama_client import OllamaClient, get_ollama_client
from .aliyun_openai_client import AliyunOpenAIClient, get_aliyun_openai_client
from .volcengine_openai_client import VolcengineOpenAIClient, get_volcengine_openai_client
from .claude_openai_client import ClaudeOpenAIClient, get_claude_openai_client

logger = logging.getLogger(__name__)


class LLMClientFactory:
    """LLM 客户端工厂类"""

    # vendor -> client getter 映射
    _VENDOR_CLIENT_MAP = {
        LLMVendor.JIEKOU: get_gemini_client,
        LLMVendor.ALIYUN: get_aliyun_openai_client,
        LLMVendor.OLLAMA: get_ollama_client,
        LLMVendor.VOLCENGINE: get_volcengine_openai_client,
        LLMVendor.CLAUDE: get_claude_openai_client,
    }

    @classmethod
    def _get_vendor_by_model(cls, model: str) -> str:
        """根据模型名称获取对应的 vendor"""
        if not model:
            return LLMVendor.JIEKOU

        model_lower = model.lower()
        for prefix, vendor in MODEL_PREFIX_VENDOR_MAP.items():
            if model_lower.startswith(prefix):
                return vendor

        # 默认使用 Gemini（兼容现有逻辑）
        logger.debug(f"模型 {model} 未匹配到特定 vendor，使用默认 {LLMVendor.JIEKOU}")
        return LLMVendor.JIEKOU

    @classmethod
    def get_client(cls, model: str) -> BaseLLMClient:
        """
        根据模型名称获取对应的 LLM 客户端

        Args:
            model: 模型名称（如 gemini-3-flash-preview, qwen3.5-plus）

        Returns:
            对应的 LLM 客户端实例
        """
        vendor = cls._get_vendor_by_model(model)
        getter = cls._VENDOR_CLIENT_MAP.get(vendor, get_gemini_client)
        client = getter()

        logger.debug(f"模型 {model} (vendor={vendor}) -> {type(client).__name__}")
        return client

    @classmethod
    def register_model_prefix(cls, prefix: str, vendor: str):
        """
        注册新的模型前缀映射

        Args:
            prefix: 模型前缀（如 "claude"）
            vendor: 供应商名称（LLMVendor 常量）
        """
        MODEL_PREFIX_VENDOR_MAP[prefix.lower()] = vendor
        logger.info(f"注册模型前缀映射: {prefix} -> {vendor}")


def get_llm_client(model: str) -> BaseLLMClient:
    """获取 LLM 客户端的便捷函数"""
    return LLMClientFactory.get_client(model)
