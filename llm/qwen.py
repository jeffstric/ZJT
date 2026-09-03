"""
⚠️ 已废弃（Deprecated）：
  - 本文件曾是早期独立的通义千问客户端，每次调用创建新的 OpenAI 客户端，且使用静态配置（启动时读取，不查数据库）。
  - 内容安全提示词改写（reduce-violation）已迁移至统一 LLM 工厂 llm.llm_client_factory.get_llm_client()，
    会自动路由供应商并从数据库热配置 + YAML 兜底读取凭据，并支持跟随剧本拆分模型改写。
  - 本文件不再被任何代码引用（llm/__init__.py 已移除其导出），计划后续删除，新功能请勿使用。
  - 如需调用 Qwen，请使用 llm.aliyun_openai_client.AliyunOpenAIClient（走工厂）。
"""
import warnings

warnings.warn(
    "llm.qwen 已废弃，请改用 llm.llm_client_factory.get_llm_client() 走统一 LLM 工厂。本文件计划后续删除。",
    DeprecationWarning,
    stacklevel=2,
)

from openai import OpenAI
from config.config_util import get_config_value, normalize_aliyun_bailian_base_url

API_KEY = get_config_value('llm', 'qwen', 'api_key', default='')
# 用户只配置基础 URL，大模型走 OpenAI 兼容接口，自动追加 /compatible-mode/v1
BASE_URL = normalize_aliyun_bailian_base_url(
    get_config_value('llm', 'qwen', 'base_url', default=None),
    for_llm=True,
)
DEFAULT_MODEL = "qwen-plus"


def call_qwen_chat(messages, model=None, temperature=0.7, max_tokens=None):
    """
    调用通义千问API进行对话（已废弃，请改用 get_llm_client()）

    Args:
        messages: 消息列表，格式为 [{"role": "user", "content": "你好"}, ...]
        model: 模型名称，默认使用配置文件中的模型
        temperature: 温度参数，控制随机性，默认0.7
        max_tokens: 最大生成token数，默认None

    Returns:
        API响应的内容字符串
    """
    try:
        client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
        )

        kwargs = {
            "model": model or DEFAULT_MODEL,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        completion = client.chat.completions.create(**kwargs)

        return completion.choices[0].message.content
    except Exception as e:
        raise Exception(f"Qwen API调用失败: {str(e)}")


async def call_qwen_chat_async(messages, model=None, temperature=0.7, max_tokens=None):
    """
    异步调用通义千问API进行对话（已废弃，请改用 get_llm_client()）

    使用 asyncio.to_thread 在线程池中执行同步调用，避免阻塞事件循环

    Args:
        messages: 消息列表，格式为 [{"role": "user", "content": "你好"}, ...]
        model: 模型名称，默认使用配置文件中的模型
        temperature: 温度参数，控制随机性，默认0.7
        max_tokens: 最大生成token数，默认None

    Returns:
        API响应的内容字符串
    """
    import asyncio
    return await asyncio.to_thread(call_qwen_chat, messages, model, temperature, max_tokens)
