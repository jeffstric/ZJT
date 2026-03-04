from openai import OpenAI
from config.config_util import get_config_value

API_KEY = get_config_value('llm', 'qwen', 'api_key', default='')
BASE_URL = get_config_value('llm', 'qwen', 'base_url', default="https://dashscope.aliyuncs.com/compatible-mode/v1")
DEFAULT_MODEL = get_config_value('llm', 'qwen', 'model', default="qwen-plus")


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
