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
from .claude_customer_client import ClaudeCustomerClient, get_claude_customer_client
from .apiai_zjt import ZJTOpenAIClient, get_zjt_openai_client

logger = logging.getLogger(__name__)


class LLMClientFactory:
    """LLM 客户端工厂类"""

    # vendor -> client getter 映射
    _VENDOR_CLIENT_MAP = {
        LLMVendor.JIEKOU: get_gemini_client,
        LLMVendor.ALIYUN: get_aliyun_openai_client,
        LLMVendor.OLLAMA: get_ollama_client,
        LLMVendor.VOLCENGINE: get_volcengine_openai_client,
        LLMVendor.CLAUDE: get_claude_customer_client,
        LLMVendor.ZJT_API: get_zjt_openai_client,
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
    def get_client(cls, model: str, vendor_id: Optional[int] = None) -> BaseLLMClient:
        """
        根据模型名称获取对应的 LLM 客户端

        Args:
            model: 模型名称（如 gemini-3-flash-preview, qwen3.5-plus）
            vendor_id: 可选的供应商 ID。若提供，优先使用该 ID 直接路由，
                      不再依赖模型名称前缀匹配。

        Returns:
            对应的 LLM 客户端实例
        """
        # 如果提供了 vendor_id，优先从数据库查询 vendor_name 直接路由
        if vendor_id is not None:
            try:
                from model.vendor import VendorDAO
                vendor_obj = VendorDAO.get_by_id(vendor_id)
                if vendor_obj and vendor_obj.vendor_name:
                    vendor = vendor_obj.vendor_name
                    getter = cls._VENDOR_CLIENT_MAP.get(vendor, get_gemini_client)
                    client = getter()
                    logger.debug(f"模型 {model} (vendor_id={vendor_id}, vendor={vendor}) -> {type(client).__name__}")
                    return client
            except Exception as e:
                logger.warning(f"根据 vendor_id={vendor_id} 查询供应商失败，回退到前缀匹配: {e}")

        # 回退：根据模型名称前缀匹配
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


def get_llm_client(model: str, vendor_id: Optional[int] = None) -> BaseLLMClient:
    """获取 LLM 客户端的便捷函数

    Args:
        model: 模型名称
        vendor_id: 可选的供应商 ID。若提供，优先使用该 ID 直接路由。
    """
    return LLMClientFactory.get_client(model, vendor_id=vendor_id)


async def get_available_models() -> dict:
    """
    获取可用的 AI 模型列表，根据 vendor 表分组

    遍历所有 vendor_model 关联，通过配置检查过滤不可用的 vendor。

    Returns:
        dict: { 'success': bool, 'models': [...] }
    """
    from config.config_util import get_dynamic_config_value
    from model.model import ModelModel
    from model.vendor import VendorDAO
    from model.vendor_model import VendorModelModel
    import logging

    logger = logging.getLogger(__name__)

    # 获取所有供应商信息
    vendors = {v.id: v for v in VendorDAO.get_all()}
    # 获取所有 vendor_model 关联
    all_vendor_models = VendorModelModel.get_all()

    # 辅助函数：检查 vendor 是否已配置（根据 vendor 类型检查对应的配置键）
    def is_vendor_configured(vendor_name):
        vendor_config_map = {
            'google': ('llm', 'google', 'api_key'),
            'claude': ('llm', 'claude', 'api_key'),
            'aliyun': ('llm', 'qwen', 'api_key'),
            'ollama': ('llm', 'ollama', 'enabled'),
            'volcengine': ('volcengine', 'api_key'),
            'zjt_api': ('api_aggregator', 'site_0', 'api_key'),
        }
        if vendor_name not in vendor_config_map:
            return True  # 未知 vendor 默认放行
        keys = vendor_config_map[vendor_name]
        value = get_dynamic_config_value(*keys, default='')
        if isinstance(value, bool):
            return value
        return bool(value and len(str(value).strip()) > 0)

    models = []
    added_model_vendor_pairs = set()  # 用于去重：跟踪 (model_id, vendor_id) 对

    # 遍历所有 vendor_model 关联，统一通过配置检查添加模型
    for vm in all_vendor_models:
        model_id = vm.model_id
        vendor_id = vm.vendor_id

        # 获取供应商信息
        vendor = vendors.get(vendor_id)
        vendor_name = vendor.vendor_name if vendor else 'unknown'

        # 检查 vendor 配置是否有效，无效则跳过
        if not is_vendor_configured(vendor_name):
            logger.info(f"[模型过滤] model_id={model_id}, vendor={vendor_name} 未配置，跳过")
            continue

        # 去重检查（配置通过后才加入集合）
        if (model_id, vendor_id) in added_model_vendor_pairs:
            logger.info(f"[去重] model_id={model_id}, vendor_id={vendor_id} 已存在，跳过")
            continue
        added_model_vendor_pairs.add((model_id, vendor_id))

        # 获取模型详情
        local_model = ModelModel.get_by_id(model_id)
        if not local_model or not local_model.supports_tools:
            continue

        # 获取 billing 配置
        input_token_threshold = None
        try:
            vendor_model = VendorModelModel.get_by_vendor_model_for_billing(
                vendor_id=vendor_id,
                model_id=model_id,
                raw_input_token=0
            )
            if vendor_model and vendor_model.input_token_threshold:
                input_token_threshold = vendor_model.input_token_threshold
        except Exception as vm_err:
            logger.warning(f"获取模型 {model_id} 的 billing 配置失败: {vm_err}")

        # Ollama 模型 ID 使用特殊格式
        model_id_str = f"ollama:{local_model.model_name}" if vendor_name == 'ollama' else str(model_id)

        models.append({
            'id': model_id_str,
            'model_id': model_id,
            'name': local_model.model_name,
            'description': local_model.note or '',
            'vendor_id': vendor_id,
            'vendor_name': vendor_name,
            'recommended': False,
            'input_token_threshold': input_token_threshold,
            'context_window': local_model.context_window,
            'supports_thinking': local_model.supports_thinking == 1
        })

    logger.info(f"添加了 {len(models)} 个模型")

    return {'success': True, 'models': models}
