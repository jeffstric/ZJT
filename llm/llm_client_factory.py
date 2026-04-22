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


async def get_available_models(token: str) -> dict:
    """
    获取可用的 AI 模型列表，根据 vendor 表分组

    从 Perseids 获取远程模型，并追加本地配置的 Qwen、Ollama、Volcengine 模型。
    返回格式与 /api/models 接口保持一致。

    Args:
        token: 用户认证令牌（Bearer token）

    Returns:
        dict: { 'success': bool, 'models': [...], 'error': str|None, 'error_code': str|None, 'token_expired': bool|None }
    """
    from typing import Optional
    from perseids_server.client import async_make_perseids_request
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
    # 按 model_id 分组，记录每个模型属于哪个 vendor
    model_vendor_map = {}
    for vm in all_vendor_models:
        if vm.model_id not in model_vendor_map:
            model_vendor_map[vm.model_id] = vm.vendor_id

    # 辅助函数：根据 vendor_name 动态查询 vendor_id（避免硬编码）
    def get_vendor_id_by_name(vendor_name):
        for vendor_id, vendor in vendors.items():
            if vendor.vendor_name == vendor_name:
                return vendor_id
        return None

    models = []
    added_model_vendor_pairs = set()  # 用于去重：跟踪 (model_id, vendor_id) 对，支持同一模型多个供应商

    # 1. 从 google 获取远程模型（vendor_id=1，google）
    headers = {'Authorization': f'Bearer {token}'}
    success, message, response_data = await async_make_perseids_request(
        endpoint='user/models',
        method='GET',
        headers=headers
    )

    if not success:
        logger.info(f"获取 Perseids 模型列表失败: {message}")
        if '无效或已过期' in message or 'token' in message.lower() or '认证' in message:
            return {
                'success': False,
                'error': message,
                'error_code': 'TOKEN_EXPIRED',
                'token_expired': True,
                'models': []
            }
    else:
        logger.info(f"Perseids 模型列表响应: {response_data}")
        remote_models = response_data.get('models', []) if isinstance(response_data, dict) else []
        for model_info in remote_models:
            model_id = model_info.get('id')
            vendor_id = model_vendor_map.get(model_id, 1)

            # 检查 (model_id, vendor_id) 对是否已添加
            if (model_id, vendor_id) in added_model_vendor_pairs:
                continue
            added_model_vendor_pairs.add((model_id, vendor_id))

            # 获取供应商信息
            vendor = vendors.get(vendor_id)
            vendor_name = vendor.vendor_name if vendor else 'jiekou'

            input_token_threshold = None
            context_window = None
            local_model = None
            try:
                if model_id and vendor_id:
                    vendor_model = VendorModelModel.get_by_vendor_model_for_billing(
                        vendor_id=vendor_id,
                        model_id=int(model_id),
                        raw_input_token=0
                    )
                    if vendor_model and vendor_model.input_token_threshold:
                        input_token_threshold = vendor_model.input_token_threshold
            except Exception as vm_err:
                logger.warning(f"获取模型 {model_id} 的 vendor_model 失败: {vm_err}")
            # 从本地 model 表获取上下文窗口配置
            try:
                local_model = ModelModel.get_by_id(int(model_id)) if model_id is not None else None
                if local_model:
                    context_window = local_model.context_window
            except Exception:
                pass

            models.append({
                'id': str(model_id),
                'model_id': model_id,
                'name': model_info.get('model_name'),
                'description': model_info.get('note') or '',
                'vendor_id': vendor_id,
                'vendor_name': vendor_name,
                'recommended': model_id == 1,
                'input_token_threshold': input_token_threshold,
                'context_window': context_window,
                'supports_thinking': local_model.supports_thinking == 1 if local_model else False
            })

    # 2. 添加阿里云 Qwen 模型（如果配置了 API Key）
    try:
        qwen_api_key = get_dynamic_config_value('llm', 'qwen', 'api_key', default='')
        if qwen_api_key:
            # 动态查询 aliyun vendor_id，避免硬编码
            aliyun_vendor_id = get_vendor_id_by_name('aliyun')
            if aliyun_vendor_id:
                qwen_model_ids = list(set([vm.model_id for vm in all_vendor_models if vm.vendor_id == aliyun_vendor_id]))
                vendor = vendors.get(aliyun_vendor_id)
                vendor_name = vendor.vendor_name if vendor else 'aliyun'
            else:
                qwen_model_ids = []
                vendor_name = 'aliyun'

            for model_id in qwen_model_ids:
                # 检查 (model_id, vendor_id) 对是否已添加
                if (model_id, aliyun_vendor_id) in added_model_vendor_pairs:
                    continue
                local_model = ModelModel.get_by_id(model_id)
                if local_model and local_model.supports_tools:
                    added_model_vendor_pairs.add((model_id, aliyun_vendor_id))

                    # 查询 vendor_model 表获取费用倍率
                    input_token_threshold = None
                    try:
                        vendor_model = VendorModelModel.get_by_vendor_model_for_billing(
                            vendor_id=aliyun_vendor_id,
                            model_id=model_id,
                            raw_input_token=0
                        )
                        if vendor_model and vendor_model.input_token_threshold:
                            input_token_threshold = vendor_model.input_token_threshold
                    except Exception as vm_err:
                        logger.warning(f"获取 Qwen 模型 {model_id} 的费用配置失败: {vm_err}")

                    models.append({
                        'id': str(model_id),
                        'model_id': model_id,
                        'name': local_model.model_name,
                        'description': local_model.note or '',
                        'vendor_id': aliyun_vendor_id,
                        'vendor_name': vendor_name,
                        'recommended': False,
                        'input_token_threshold': input_token_threshold,
                        'context_window': local_model.context_window,
                        'supports_thinking': local_model.supports_thinking == 1
                    })
            logger.info(f"添加了 {len([m for m in models if m.get('vendor_id') == 2])} 个阿里云 Qwen 模型")
    except Exception as e:
        logger.warning(f"获取阿里云 Qwen 模型列表失败: {e}")

    # 3. 添加 Ollama 本地模型（如果启用）
    try:
        ollama_enabled = get_dynamic_config_value('llm', 'ollama', 'enabled', default=False)
        if ollama_enabled:
            # 动态查询 ollama vendor_id，避免硬编码
            ollama_vendor_id = get_vendor_id_by_name('ollama')
            if ollama_vendor_id:
                ollama_model_ids = [vm.model_id for vm in all_vendor_models if vm.vendor_id == ollama_vendor_id]
                vendor = vendors.get(ollama_vendor_id)
                vendor_name = vendor.vendor_name if vendor else 'ollama'
            else:
                ollama_model_ids = []
                vendor_name = 'ollama'

            for model_id in ollama_model_ids:
                # 检查 (model_id, vendor_id) 对是否已添加
                if (model_id, ollama_vendor_id) in added_model_vendor_pairs:
                    continue
                local_model = ModelModel.get_by_id(model_id)
                if local_model and local_model.supports_tools:
                    added_model_vendor_pairs.add((model_id, ollama_vendor_id))

                    # 查询 vendor_model 表获取费用倍率
                    input_token_threshold = None
                    try:
                        vendor_model = VendorModelModel.get_by_vendor_model_for_billing(
                            vendor_id=ollama_vendor_id,
                            model_id=model_id,
                            raw_input_token=0
                        )
                        if vendor_model and vendor_model.input_token_threshold:
                            input_token_threshold = vendor_model.input_token_threshold
                    except Exception as vm_err:
                        logger.warning(f"获取 Ollama 模型 {model_id} 的费用配置失败: {vm_err}")

                    models.append({
                        'id': f"ollama:{local_model.model_name}",
                        'model_id': model_id,
                        'name': local_model.model_name,
                        'description': local_model.note or '',
                        'vendor_id': ollama_vendor_id,
                        'vendor_name': vendor_name,
                        'recommended': False,
                        'input_token_threshold': input_token_threshold,
                        'context_window': local_model.context_window,
                        'supports_thinking': local_model.supports_thinking == 1
                    })
            logger.info(f"添加了 {len(ollama_model_ids)} 个 Ollama 模型")
    except Exception as e:
        logger.warning(f"获取 Ollama 模型列表失败: {e}")

    # 4. 添加火山引擎 Doubao 模型（如果配置了 API Key）
    try:
        volcengine_api_key = get_dynamic_config_value('volcengine', 'api_key', default='')
        if volcengine_api_key:
            volcengine_vendor_id = get_vendor_id_by_name('volcengine')
            if volcengine_vendor_id:
                volcengine_model_ids = list(set([vm.model_id for vm in all_vendor_models if vm.vendor_id == volcengine_vendor_id]))
                vendor = vendors.get(volcengine_vendor_id)
                vendor_name = vendor.vendor_name if vendor else 'volcengine'
            else:
                volcengine_model_ids = []
                vendor_name = 'volcengine'

            for model_id in volcengine_model_ids:
                # 检查 (model_id, vendor_id) 对是否已添加
                if (model_id, volcengine_vendor_id) in added_model_vendor_pairs:
                    continue
                local_model = ModelModel.get_by_id(model_id)
                if local_model and local_model.supports_tools:
                    added_model_vendor_pairs.add((model_id, volcengine_vendor_id))

                    input_token_threshold = None
                    try:
                        vendor_model = VendorModelModel.get_by_vendor_model_for_billing(
                            vendor_id=volcengine_vendor_id,
                            model_id=model_id,
                            raw_input_token=0
                        )
                        if vendor_model and vendor_model.input_token_threshold:
                            input_token_threshold = vendor_model.input_token_threshold
                    except Exception as vm_err:
                        logger.warning(f"获取 Volcengine 模型 {model_id} 的费用配置失败: {vm_err}")

                    models.append({
                        'id': str(model_id),
                        'model_id': model_id,
                        'name': local_model.model_name,
                        'description': local_model.note or '',
                        'vendor_id': volcengine_vendor_id,
                        'vendor_name': vendor_name,
                        'recommended': False,
                        'input_token_threshold': input_token_threshold,
                        'context_window': local_model.context_window,
                        'supports_thinking': local_model.supports_thinking == 1
                    })
            logger.info(f"添加了 {len([m for m in models if m.get('vendor_name') == 'volcengine'])} 个火山引擎 Doubao 模型")
    except Exception as e:
        logger.warning(f"获取火山引擎 Doubao 模型列表失败: {e}")

    # 5. 添加 ZJT API 模型（如果配置了 API Key）
    try:
        zjt_api_key = get_dynamic_config_value('api_aggregator', 'site_0', 'api_key', default='')
        if zjt_api_key:
            # 动态查询 zjt_api vendor_id，避免硬编码
            zjt_api_vendor_id = get_vendor_id_by_name('zjt_api')
            if zjt_api_vendor_id:
                zjt_model_ids = list(set([vm.model_id for vm in all_vendor_models if vm.vendor_id == zjt_api_vendor_id]))
                vendor = vendors.get(zjt_api_vendor_id)
                vendor_name = vendor.vendor_name if vendor else 'zjt_api'
            else:
                zjt_model_ids = []
                vendor_name = 'zjt_api'

            for model_id in zjt_model_ids:
                # 检查 (model_id, vendor_id) 对是否已添加
                if (model_id, zjt_api_vendor_id) in added_model_vendor_pairs:
                    continue
                local_model = ModelModel.get_by_id(model_id)
                if local_model and local_model.supports_tools:
                    added_model_vendor_pairs.add((model_id, zjt_api_vendor_id))

                    # 查询 vendor_model 表获取费用倍率
                    input_token_threshold = None
                    try:
                        vendor_model = VendorModelModel.get_by_vendor_model_for_billing(
                            vendor_id=zjt_api_vendor_id,
                            model_id=model_id,
                            raw_input_token=0
                        )
                        if vendor_model and vendor_model.input_token_threshold:
                            input_token_threshold = vendor_model.input_token_threshold
                    except Exception as vm_err:
                        logger.warning(f"获取 ZJT API 模型 {model_id} 的费用配置失败: {vm_err}")

                    models.append({
                        'id': str(model_id),
                        'model_id': model_id,
                        'name': local_model.model_name,
                        'description': local_model.note or '',
                        'vendor_id': zjt_api_vendor_id,
                        'vendor_name': vendor_name,
                        'recommended': False,
                        'input_token_threshold': input_token_threshold,
                        'context_window': local_model.context_window,
                        'supports_thinking': local_model.supports_thinking == 1
                    })
            logger.info(f"添加了 {len([m for m in models if m.get('vendor_name') == 'zjt_api'])} 个 ZJT API 模型")
    except Exception as e:
        logger.warning(f"获取 ZJT API 模型列表失败: {e}")

    return {'success': True, 'models': models}
