"""
⚠️ 旧版通义千问客户端（遗留代码）：
  - 本文件是早期独立实现，每次调用都创建新的 OpenAI 客户端，且使用静态配置（启动时读取）
  - 新版推荐使用 aliyun_openai_client.py（AliyunOpenAIClient），支持动态刷新配置
  - 本文件目前仍被部分旧代码引用，新功能请勿使用此文件
"""
from openai import OpenAI
from config.config_util import get_config_value

API_KEY = get_config_value('llm', 'qwen', 'api_key', default='')
BASE_URL = get_config_value('llm', 'qwen', 'base_url', default="https://dashscope.aliyuncs.com/compatible-mode/v1")
DEFAULT_MODEL = "qwen-plus"


def call_qwen_chat(messages, model=None, temperature=0.7, max_tokens=None):
    """
    调用通义千问API进行对话
    
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
    异步调用通义千问API进行对话
    
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
