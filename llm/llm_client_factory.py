"""
LLM 客户端工厂类
根据模型类型自动选择对应的 driver（Gemini 或 OpenAI）
"""
import logging
from typing import Optional

from .base_llm_client import BaseLLMClient
from .gemini_client import GeminiClient, get_gemini_client
from .openai_client import OpenAIClient, get_openai_client
from .ollama_client import OllamaClient, get_ollama_client

logger = logging.getLogger(__name__)


class LLMClientFactory:
    """LLM 客户端工厂类"""

    # 模型前缀到 driver 的映射
    _MODEL_PREFIX_MAP = {
        "gemini": "gemini",
        "qwen": "openai",
        "gpt": "openai",
        "claude": "openai",  # 未来的 Claude 支持
        "ollama": "ollama",  # Ollama 本地模型
    }

    @classmethod
    def get_client(cls, model: str) -> BaseLLMClient:
        """
        根据模型名称获取对应的 LLM 客户端

        Args:
            model: 模型名称（如 gemini-3-flash-preview, qwen3.5-plus）

        Returns:
            对应的 LLM 客户端实例（GeminiClient 或 OpenAIClient）
        """
        if not model:
            logger.warning("模型名称为空，使用默认 Gemini 客户端")
            return get_gemini_client()

        # 检测模型类型
        model_lower = model.lower()

        # 检查前缀匹配
        for prefix, driver in cls._MODEL_PREFIX_MAP.items():
            if model_lower.startswith(prefix):
                if driver == "gemini":
                    logger.debug(f"模型 {model} 使用 Gemini driver")
                    return get_gemini_client()
                elif driver == "openai":
                    logger.debug(f"模型 {model} 使用 OpenAI driver")
                    return get_openai_client()
                elif driver == "ollama":
                    logger.debug(f"模型 {model} 使用 Ollama driver")
                    return get_ollama_client()

        # 默认使用 Gemini（兼容现有逻辑）
        logger.debug(f"模型 {model} 未匹配到特定 driver，使用默认 Gemini driver")
        return get_gemini_client()

    @classmethod
    def get_client_by_type(cls, driver_type: str) -> BaseLLMClient:
        """
        根据 driver 类型获取客户端

        Args:
            driver_type: driver 类型（"gemini"、"openai" 或 "ollama"）

        Returns:
            对应的 LLM 客户端实例
        """
        if driver_type == "openai":
            return get_openai_client()
        elif driver_type == "ollama":
            return get_ollama_client()
        else:
            return get_gemini_client()

    @classmethod
    def register_model_prefix(cls, prefix: str, driver: str):
        """
        注册新的模型前缀映射

        Args:
            prefix: 模型前缀（如 "claude"）
            driver: driver 类型（"gemini" 或 "openai"）
        """
        cls._MODEL_PREFIX_MAP[prefix.lower()] = driver
        logger.info(f"注册模型前缀映射: {prefix} -> {driver}")


def get_llm_client(model: str) -> BaseLLMClient:
    """获取 LLM 客户端的便捷函数"""
    return LLMClientFactory.get_client(model)
