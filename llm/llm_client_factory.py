"""
LLM 客户端工厂类
根据模型类型自动选择对应的 driver（Gemini、AliyunOpenAI、VolcengineOpenAI、Ollama）

映射关系：
  模型前缀 → vendor（config/constant.py 中 MODEL_PREFIX_VENDOR_MAP 定义）
  vendor → client getter（本文件 _VENDOR_CLIENT_MAP 定义）
"""
import asyncio
import logging
from typing import Optional

from config.constant import LLMVendor, MODEL_PREFIX_VENDOR_MAP
from .base_llm_client import BaseLLMClient
from .gemini_client import GeminiClient, get_gemini_client
from .ollama_client import OllamaClient, get_ollama_client
from .vllm_client import VLLMClient, get_vllm_client
from .aliyun_openai_client import AliyunOpenAIClient, get_aliyun_openai_client
from .volcengine_openai_client import VolcengineOpenAIClient, get_volcengine_openai_client
from .claude_customer_client import ClaudeCustomerClient, get_claude_customer_client
from .zjt_openai_client import ZJTOpenAIClient, get_zjt_openai_client
from .openai_deepseek import DeepSeekOpenAIClient, get_deepseek_openai_client
from .openai_agnes import AgnesOpenAIClient, get_agnes_openai_client
from .openai_mimo import MimoOpenAIClient, get_mimo_openai_client

logger = logging.getLogger(__name__)

# 本地服务供应商（无云端凭据，模型 ID 下发时使用 "vendor:模型名" 前缀）
_LOCAL_SERVICE_VENDORS = (LLMVendor.OLLAMA, LLMVendor.VLLM)


class LLMClientFactory:
    """LLM 客户端工厂类"""

    # vendor -> client getter 映射
    _VENDOR_CLIENT_MAP = {
        LLMVendor.JIEKOU: get_gemini_client,
        LLMVendor.ALIYUN: get_aliyun_openai_client,
        LLMVendor.OLLAMA: get_ollama_client,
        LLMVendor.VLLM: get_vllm_client,
        LLMVendor.VOLCENGINE: get_volcengine_openai_client,
        LLMVendor.CLAUDE: get_claude_customer_client,
        LLMVendor.ZJT_API: get_zjt_openai_client,
        LLMVendor.DEEPSEEK: get_deepseek_openai_client,
        LLMVendor.AGNES: get_agnes_openai_client,
        LLMVendor.MIMO: get_mimo_openai_client,
    }

    # 历史数据中 Gemini 供应商（LLMVendor.JIEKOU）可能被命名为 google；
    # 普通调用经模型前缀回退不受影响，精确路由（安全审核）需要别名兼容。
    _EXACT_VENDOR_ALIASES = {"google": LLMVendor.JIEKOU}

    @classmethod
    def _get_vendor_by_model(cls, model: str) -> str:
        """根据模型名称获取对应的 vendor

        优先级：模型名前缀匹配 > 按模型名查库反查 vendor_model（本地服务等
        无前缀约定的模型）> 默认 Gemini（兼容现有逻辑）。
        """
        if not model:
            return LLMVendor.JIEKOU

        model_lower = model.lower()
        for prefix, vendor in MODEL_PREFIX_VENDOR_MAP.items():
            if model_lower.startswith(prefix):
                return vendor

        # 前缀未命中：按模型名查库反查所属供应商（模型名全局唯一）。历史版本
        # 依赖本地服务模型 id 携带 "vendor:模型名" 前缀路由；id 数值化后，
        # 调用方不传 vendor_id 的场景由此兜底，避免误路由到默认 JIEKOU。
        try:
            from model.model import ModelModel
            from model.vendor import VendorDAO
            from model.vendor_model import VendorModelModel

            local_model = ModelModel.get_by_name(str(model).strip())
            if local_model:
                vendor_id = VendorModelModel.get_vendor_id_by_model_id(local_model.id)
                if vendor_id:
                    vendor_obj = VendorDAO.get_by_id(vendor_id)
                    if vendor_obj and vendor_obj.vendor_name:
                        logger.debug(
                            f"模型 {model} 前缀未命中，按库反查路由到 vendor={vendor_obj.vendor_name}"
                        )
                        return vendor_obj.vendor_name
        except Exception as e:
            logger.debug(f"模型 {model} 按库反查 vendor 失败，回退默认: {e}")

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
                      例外：model 为 "vendor:模型名" 显式本地格式（vllm:/ollama:）时，
                      前缀优先于 vendor_id，避免本地模型名被透传给云端 API。

        Returns:
            对应的 LLM 客户端实例
        """
        # 防御层：本地服务显式前缀（vllm:/ollama:）优先于 vendor_id 路由
        local_prefix = None
        if isinstance(model, str) and ':' in model:
            prefix = model.split(':', 1)[0].lower()
            if prefix in _LOCAL_SERVICE_VENDORS:
                local_prefix = prefix

        if vendor_id is not None:
            try:
                from model.vendor import VendorDAO
                vendor_obj = VendorDAO.get_by_id(vendor_id)
                if vendor_obj and vendor_obj.vendor_name:
                    vendor = vendor_obj.vendor_name
                    if local_prefix and local_prefix != vendor:
                        logger.warning(
                            f"模型 {model} 的本地前缀 {local_prefix} 与 vendor_id={vendor_id} "
                            f"解析的供应商 {vendor} 冲突，按前缀路由到本地服务"
                        )
                    else:
                        getter = cls._VENDOR_CLIENT_MAP.get(vendor, get_gemini_client)
                        client = getter()
                        logger.debug(f"模型 {model} (vendor_id={vendor_id}, vendor={vendor}) -> {type(client).__name__}")
                        return client
            except Exception as e:
                logger.warning(f"根据 vendor_id={vendor_id} 查询供应商失败，回退到前缀匹配: {e}")

        if local_prefix:
            getter = cls._VENDOR_CLIENT_MAP[local_prefix]
            client = getter()
            logger.debug(f"模型 {model} 按本地前缀 {local_prefix} 路由 -> {type(client).__name__}")
            return client

        # 回退：根据模型名称前缀匹配
        vendor = cls._get_vendor_by_model(model)
        getter = cls._VENDOR_CLIENT_MAP.get(vendor, get_gemini_client)
        client = getter()

        logger.debug(f"模型 {model} (vendor={vendor}) -> {type(client).__name__}")
        return client

    @classmethod
    def get_client_for_exact_vendor(cls, vendor_name: str) -> BaseLLMClient:
        """按明确的供应商名称取客户端，任何异常配置都不回退。

        普通模型调用仍由 :meth:`get_client` 保持历史兼容行为；安全审核等
        fail-closed 场景必须先自行校验数据库路由，再调用本方法。
        """

        if not isinstance(vendor_name, str) or not vendor_name:
            raise ValueError("LLM 供应商名称为空")
        resolved = cls._EXACT_VENDOR_ALIASES.get(vendor_name, vendor_name)
        getter = cls._VENDOR_CLIENT_MAP.get(resolved)
        if getter is None:
            raise ValueError("LLM 供应商类型不受支持")
        return getter()

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
    # 防御：部分前端入口会把 model 传成对象（{name, model, model_id, vendor_id}），
    # 这里拍平为字符串，避免 Gemini 路由把 dict 序列化进 URL 触发 404。
    if isinstance(model, dict):
        model = model.get("model") or model.get("name") or ""
    elif model is not None and not isinstance(model, str):
        model = str(model)
    return LLMClientFactory.get_client(model, vendor_id=vendor_id)


def is_llm_client_configured(client: BaseLLMClient) -> bool:
    """判断 LLM 客户端是否已配置可用。

    Ollama/vLLM 等本地部署 client 无需真实 api_key（无需联网鉴权），
    但受 llm.<vendor>.enabled 开关控制：未启用时不能判为可用，
    否则 H3 等回退链路会反复选中已禁用的本地模型，调用失败后直接退回
    原始提示词，而不会继续切换到下一个云端候选。
    云端供应商（gemini/claude/aliyun/deepseek/volcengine/zjt/agnes）必须配置非空 api_key。

    供 H3 提示词优化等场景做模型回退判定，避免对未配置供应商发起必败调用。
    """
    if isinstance(client, (OllamaClient, VLLMClient)):
        return bool(getattr(client, 'enabled', False))
    return bool(getattr(client, 'api_key', ''))


# 供应商 -> 凭据配置键（system_config 动态配置）。本地服务供应商用 enabled 开关，
# 其余为 api_key。新增供应商时同步维护，否则该供应商默认放行（视为已配置）。
_VENDOR_CREDENTIAL_CONFIG_KEYS = {
    'google': ('llm', 'google', 'api_key'),
    'claude': ('llm', 'claude', 'api_key'),
    'aliyun': ('llm', 'qwen', 'api_key'),
    'ollama': ('llm', 'ollama', 'enabled'),
    'vllm': ('llm', 'vllm', 'enabled'),
    'volcengine': ('volcengine', 'api_key'),
    'zjt_api': ('api_aggregator', 'site_0', 'api_key'),
    'deepseek': ('llm', 'deepseek', 'api_key'),
    'agnes': ('llm', 'agnes', 'api_key'),
    'mimo': ('llm', 'mimo', 'api_key'),
}


def is_vendor_configured(vendor_name: str) -> bool:
    """检查供应商凭据是否已配置（根据 vendor 类型检查对应的配置键）。"""
    from config.config_util import get_dynamic_config_value

    keys = _VENDOR_CREDENTIAL_CONFIG_KEYS.get(vendor_name)
    if keys is None:
        return True  # 未知 vendor 默认放行
    value = get_dynamic_config_value(*keys, default='')
    if isinstance(value, bool):
        return value
    return bool(value and len(str(value).strip()) > 0)


def get_vendor_model_unusable_reason(vendor_id, model_id) -> Optional[str]:
    """校验显式 (vendor_id, model_id) 路由是否可用；可用返回 None，否则返回中文原因。

    供任务创建入口前置拦截：模型列表接口只会下发「vendor_model 关联存在 +
    供应商凭据已配置」的组合，前端显式传了不可用组合说明是过期选择或手工
    请求；放行只会把失败推迟到 LLM 调用期（PM 链路还曾把失败吞成
    completed），不如在创建时直接 400。
    注意「凭据已配置但平台侧未开通该模型」（如火山账号未开 deepseek-v4-flash）
    入口无法判断，由调用期 InvalidEndpointOrModel.NotFound 的明确报错兜底。

    同步查库函数，async 接口调用方须用 asyncio.to_thread 包裹。
    校验自身异常时不阻塞任务创建（与工厂路由的容错口径一致），返回 None 放行。
    """
    try:
        vendor_id_int = int(vendor_id)
    except (TypeError, ValueError):
        return None
    try:
        from model.vendor import VendorDAO
        from model.vendor_model import VendorModelModel

        vendor = VendorDAO.get_by_id(vendor_id_int)
        if not vendor or not vendor.vendor_name:
            return f"供应商 vendor_id={vendor_id_int} 不存在，请重新选择模型"
        try:
            model_id_int = int(model_id)
        except (TypeError, ValueError):
            return None
        if not VendorModelModel.get_by_vendor_model(vendor_id_int, model_id_int):
            return (
                f"模型未关联供应商 {vendor.vendor_name}，请重新选择对话模型"
            )
        if not is_vendor_configured(vendor.vendor_name):
            return (
                f"供应商 {vendor.vendor_name} 的 API Key 未配置，请重新选择对话模型"
            )
        return None
    except Exception as e:
        logger.warning(
            f"校验供应商模型路由失败（放行）: vendor_id={vendor_id}, model_id={model_id}: {e}"
        )
        return None


def _get_available_models_sync() -> dict:
    """同步实现：获取可用的 AI 模型列表（在 asyncio.to_thread 线程池中调用）。"""
    from model.model import ModelModel
    from model.vendor import VendorDAO
    from model.vendor_model import VendorModelModel

    # 获取所有供应商信息
    vendors = {v.id: v for v in VendorDAO.get_all()}
    # 获取所有 vendor_model 关联
    all_vendor_models = VendorModelModel.get_all()

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
            # logger.debug(f"[模型过滤] model_id={model_id}, vendor={vendor_name} 未配置，跳过")
            continue

        # 去重检查（配置通过后才加入集合）
        if (model_id, vendor_id) in added_model_vendor_pairs:
            # logger.debug(f"[去重] model_id={model_id}, vendor_id={vendor_id} 已存在，跳过")
            continue
        added_model_vendor_pairs.add((model_id, vendor_id))

        # 获取模型详情
        local_model = ModelModel.get_by_id(model_id)
        if not local_model or not local_model.supports_tools or not local_model.enabled:
            continue

        # 获取 billing 配置（按当前北京时间时段取价，配了峰谷则反映当前价）
        input_token_threshold = None
        try:
            from utils.billing_period import get_billing_period
            vendor_model = VendorModelModel.get_by_vendor_model_for_billing(
                vendor_id=vendor_id,
                model_id=model_id,
                raw_input_token=0,
                time_period=get_billing_period(None),
            )
            if vendor_model and vendor_model.input_token_threshold:
                input_token_threshold = vendor_model.input_token_threshold
        except Exception as vm_err:
            logger.warning(f"获取模型 {model_id} 的 billing 配置失败: {vm_err}")

        # id 统一下发数值库 ID 字符串。历史版本对本地服务供应商（Ollama/vLLM）
        # 曾下发 "vendor:模型名" 复合串供工厂按前缀路由——工厂现已支持 vendor_id
        # 优先路由，前端也统一以 model_id + vendor_id 数值对选择模型，复合串
        # 失去存在理由（且 vendor_name 无唯一索引，复合串本身有歧义隐患）。
        # 存量数据中的历史复合串由 resolve_composite_model_ref 读路径兼容。
        model_id_str = str(model_id)

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
            'supports_thinking': local_model.supports_thinking == 1,
            'supports_vl': local_model.supports_vl == 1
        })

    # logger.info(f"添加了 {len(models)} 个模型")

    return {'success': True, 'models': models}


async def get_available_models() -> dict:
    """
    获取可用的 AI 模型列表，根据 vendor 表分组

    遍历所有 vendor_model 关联，通过配置检查过滤不可用的 vendor。
    同步查库放线程池（asyncio.to_thread），避免 async 接口内同步查库阻塞 Event Loop。

    Returns:
        dict: { 'success': bool, 'models': [...] }
    """
    return await asyncio.to_thread(_get_available_models_sync)


def resolve_composite_model_ref(model_ref: str) -> tuple:
    """
    将 "vendor:模型名" 复合模型标识还原为 (vendor_id, model_db_id)。

    本地服务供应商（Ollama/vLLM）的模型经 /api/models 下发时 id 字段使用
    "vendor:模型名" 前缀格式（见 _get_available_models_sync），历史版本前端
    会把该复合串当作 model_id 回传（如剧本节点拆分请求）。按首个冒号拆分后
    查库还原数值 ID；vendor/model/关联任一缺失或查询异常时返回 (None, None)。

    同步查库函数，async 接口调用方须用 asyncio.to_thread 包裹。
    """
    ref = str(model_ref or '').strip()
    if not ref or ':' not in ref:
        return None, None
    # /api/models 的 id 已数值化（不再产出复合串）；此处命中说明请求/存储里
    # 仍是历史复合串（存量 workflow_data、config_json、旧客户端在途请求），
    # 兼容还原但告警观察，清零后可移除本兼容层
    logger.warning(f"[复合模型标识] 收到历史复合串并兼容还原: {ref}（/api/models 已数值化，请排查数据来源）")
    vendor_name, _, model_name = ref.partition(':')
    vendor_name = vendor_name.strip()
    model_name = model_name.strip()
    if not vendor_name or not model_name:
        return None, None
    try:
        from model.model import ModelModel
        from model.vendor import VendorDAO
        from model.vendor_model import VendorModelModel

        vendor = VendorDAO.get_by_name(vendor_name)
        if not vendor:
            return None, None
        local_model = ModelModel.get_by_name(model_name)
        if not local_model:
            return None, None
        # 复合串由 vendor_model 关联生成，关联缺失说明供应商或模型已下架，拒绝猜测
        if not VendorModelModel.get_by_vendor_model(vendor.id, local_model.id):
            return None, None
        return vendor.id, local_model.id
    except Exception as e:
        logger.warning(f"解析复合模型标识失败: {model_ref}: {e}")
        return None, None


def normalize_model_selection_refs(
    model_id=None,
    vendor_id=None,
    default_vendor_id: int = 1,
) -> tuple:
    """
    归一化前端/存储回传的 model_id / vendor_id，返回 (numeric_model_id, resolved_vendor_id)。

    统一各入口的归一化规则（此前 parse-script 用 vendor==1 哨兵、发布拆分用
    falsy 判断，条件分叉导致复合串场景互相覆盖）：
    1. model_id 为数字（含数字串）直接转 int；否则按 "vendor:模型名" 复合串
       调 resolve_composite_model_ref 还原（还原失败返回 None，走调用方默认模型）。
    2. vendor 解析优先级：显式非默认 vendor（>0 且 != default_vendor_id） >
       复合串还原出的 vendor > 按数值 model_id 反查 vendor_model > default_vendor_id。
       显式传默认值（如前端未选择时回传 1）与缺省同权，允许被模型实际归属修正。

    同步查库函数，async 接口调用方须用 asyncio.to_thread 包裹。
    """
    explicit_vendor_id = None
    if vendor_id not in (None, ''):
        try:
            parsed = int(vendor_id)
            if parsed > 0:
                explicit_vendor_id = parsed
        except (TypeError, ValueError):
            pass

    numeric_model_id = None
    composite_vendor_id = None
    if model_id not in (None, ''):
        try:
            numeric_model_id = int(model_id)
        except (TypeError, ValueError):
            composite_vendor_id, numeric_model_id = resolve_composite_model_ref(
                str(model_id)
            )

    if explicit_vendor_id is not None and explicit_vendor_id != default_vendor_id:
        resolved_vendor_id = explicit_vendor_id
    elif composite_vendor_id:
        resolved_vendor_id = composite_vendor_id
    elif numeric_model_id:
        try:
            from model.vendor_model import VendorModelModel
            resolved_vendor_id = VendorModelModel.get_vendor_id_by_model_id(
                numeric_model_id
            ) or default_vendor_id
        except Exception as e:
            logger.warning(f"按模型反查 vendor 失败: model_id={numeric_model_id}: {e}")
            resolved_vendor_id = default_vendor_id
    else:
        resolved_vendor_id = default_vendor_id
    return numeric_model_id, resolved_vendor_id


def coerce_model_id_or_none(model_id) -> Optional[int]:
    """
    宽容地把存储/请求里的 model_id 归一为数值 ID，失败（含无法还原的
    复合串）返回 None 而不抛异常。

    供偏好解析等同步路径使用：历史存储可能把 "vendor:模型名" 复合串当
    model_id 存下，裸 int() 会 ValueError 使整个接口 500。
    """
    if model_id in (None, ''):
        return None
    try:
        return int(model_id)
    except (TypeError, ValueError):
        _, numeric_model_id = resolve_composite_model_ref(str(model_id))
        return numeric_model_id
