"""
Gemini API 客户端 - 统一的 Gemini 原生 API 调用接口
供 PM Agent 和 Expert Agent 使用
"""
import os
import json
import uuid
import logging
import yaml
import requests
from pathlib import Path
from typing import Dict, List, Any, Optional
from config_util import get_config_path
from perseids_client import make_perseids_request

# 导入日志函数
try:
    from chat_app import log_api_interaction
except ImportError:
    # 如果导入失败，定义一个简单的替代函数
    def log_api_interaction(message: str, data: Any = None):
        pass

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 读取配置文件
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_file = get_config_path()
with open(os.path.join(APP_DIR, config_file), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# 优先使用 jiekou 配置，如果没有则使用 google 配置
jiekou_config = config.get('jiekou', {})
google_config = config.get('google', {})

API_KEY = jiekou_config.get('api_key') or google_config.get('api_key')
BASE_URL = jiekou_config.get('base_url') or google_config.get('gemini_base_url')


class GeminiClient:
    """Gemini 原生 API 客户端"""
    
    def __init__(self):
        """初始化 Gemini 客户端"""
        self.api_key = API_KEY
        self.base_url = BASE_URL
        
        if not self.api_key or not self.base_url:
            logger.warning("Gemini API Key 或 Base URL 未配置")
        else:
            logger.info(f"GeminiClient initialized: base_url={self.base_url}")

    def _convert_to_gemini_format(self, messages, tools=None):
        """将OpenAI格式的消息转换为Gemini原生格式"""
        gemini_data = {
            "contents": [],
            "generationConfig": {}
        }
        
        # 转换tools
        if tools:
            gemini_tools = []
            function_declarations = []
            for tool in tools:
                if tool.get("type") == "function":
                    func = tool["function"]
                    function_declarations.append({
                        "name": func["name"],
                        "description": func.get("description", ""),
                        "parameters": func.get("parameters", {})
                    })
            if function_declarations:
                gemini_tools.append({"functionDeclarations": function_declarations})
            gemini_data["tools"] = gemini_tools

        for msg in messages:
            role = msg.get("role")
            
            if role == "system":
                # Gemini使用systemInstruction
                gemini_data["systemInstruction"] = {
                    "parts": [{"text": msg["content"]}]
                }
            elif role == "user":
                gemini_data["contents"].append({
                    "role": "user",
                    "parts": [{"text": msg["content"]}]
                })
            elif role == "assistant":
                parts = []
                if msg.get("content"):
                    parts.append({"text": msg["content"]})
                
                # 处理tool_calls
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        func = tc["function"]
                        try:
                            args = json.loads(func["arguments"]) if isinstance(func["arguments"], str) else func["arguments"]
                        except:
                            args = {}
                        
                        function_call_part = {
                            "functionCall": {
                                "name": func["name"],
                                "args": args
                            }
                        }
                        
                        # 根据Gemini文档：只有第一个函数调用需要thoughtSignature
                        # 并行调用中的后续函数不需要签名
                        is_first_function = len(parts) == 0 or not any('functionCall' in part for part in parts)
                        
                        if is_first_function:
                            # 获取thought_signature
                            signature_to_use = msg.get("thought_signature")
                            
                            # 如果当前消息没有thought_signature，尝试从最近的assistant消息中获取
                            if not signature_to_use:
                                for prev_msg in reversed(messages):
                                    if prev_msg.get("role") == "assistant" and prev_msg.get("thought_signature"):
                                        signature_to_use = prev_msg["thought_signature"]
                                        log_api_interaction(f"[Gemini格式转换] 为第一个函数 {func['name']} 使用历史thought_signature")
                                        break
                            
                            if signature_to_use:
                                # 根据文档：thoughtSignature应该与functionCall同级，在part内部
                                function_call_part["thoughtSignature"] = signature_to_use
                                log_api_interaction(f"[Gemini格式转换] 为第一个函数 {func['name']} 添加thought_signature")
                            else:
                                log_api_interaction(f"[Gemini格式转换] 警告：第一个函数 {func['name']} 缺少thought_signature")
                        else:
                            log_api_interaction(f"[Gemini格式转换] 并行函数 {func['name']} 跳过thought_signature（符合文档规范）")
                        
                        parts.append(function_call_part)
                
                if parts:
                    gemini_content = {
                        "role": "model",
                        "parts": parts
                    }
                    
                    # 根据Gemini文档：文本响应也应该包含thoughtSignature
                    if msg.get("thought_signature") and not msg.get("tool_calls") and msg.get("content"):
                        # 为文本内容添加thoughtSignature（与text同级）
                        if parts and "text" in parts[0]:
                            parts[0]["thoughtSignature"] = msg["thought_signature"]
                            log_api_interaction("[Gemini格式转换] 为文本内容添加thought_signature")
                    
                    gemini_data["contents"].append(gemini_content)
            elif role == "tool":
                # Gemini要求多个functionResponse在同一个消息中
                func_name = msg.get("name", "unknown")
                
                try:
                    response_data = json.loads(msg["content"]) if isinstance(msg["content"], str) else msg["content"]
                except:
                    response_data = {"result": msg["content"]}
                
                func_response_part = {
                    "functionResponse": {
                        "name": func_name,
                        "response": response_data
                    }
                }
                
                # 检查上一个消息是否也是function，如果是则合并
                if gemini_data["contents"] and gemini_data["contents"][-1].get("role") == "function":
                    gemini_data["contents"][-1]["parts"].append(func_response_part)
                else:
                    gemini_data["contents"].append({
                        "role": "function",
                        "parts": [func_response_part]
                    })
        
        return gemini_data
    
    def call_api(
        self, 
        model: str,
        messages: List[Dict[str, str]], 
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 65536,
        auth_token: Optional[str] = None,
        vendor_id: Optional[int] = None,
        model_id: Optional[int] = None
    ) -> Any:
        """
        调用 Gemini 原生 API
        
        Args:
            model: 模型名称（如 gemini-3-flash-preview）
            messages: OpenAI 格式的消息列表
            tools: 工具定义列表
            temperature: 温度参数
            max_tokens: 最大输出 token 数
            auth_token: 认证token
            vendor_id: 商家ID
            model_id: 模型ID
        Returns:
            标准格式的响应对象
        """
        if not self.api_key or not self.base_url:
            raise Exception("Gemini API Key 或 Base URL 未配置")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # 转换为 Gemini 原生格式
        gemini_payload = self._convert_to_gemini_format(messages, tools)
        gemini_payload["generationConfig"] = {
            "maxOutputTokens": max_tokens,
            "temperature": temperature
        }
        
        # 构建 URL
        base_url = self.base_url.rstrip('/')
        if base_url.endswith('/openai'):
            base_url = base_url[:-7]
        
        # 移除 model 中的 "gemini/" 前缀以避免重复路径
        model_name = model.replace("gemini/", "", 1) if "/" in model else model
        
        url = f"{base_url}/gemini/v1/models/{model_name}:generateContent"
        logger.info(f"Gemini API URL: {url}")
        logger.info(f"Gemini API model: {model}")
        logger.info(f"Gemini API temperature: {temperature}")
        logger.info(f"Gemini API max_tokens: {max_tokens}")
        
        # 记录请求 payload
        logger.info(f"Gemini API contents count: {len(gemini_payload.get('contents', []))}")
        logger.info("="*80)
        for i, content in enumerate(gemini_payload.get('contents', [])):
            role = content.get('role', 'unknown')
            parts_count = len(content.get('parts', []))
            logger.info(f"Content[{i}]: role={role}, parts={parts_count}")
            
            # 完整记录每个 part 的内容
            for j, part in enumerate(content.get('parts', [])):
                if 'text' in part:
                    logger.info(f"  Part[{j}] (text, {len(part['text'])} chars):")
                    logger.info(f"{part['text']}")
                elif 'functionCall' in part:
                    logger.info(f"  Part[{j}] (functionCall): {part['functionCall'].get('name', 'unknown')}")
                elif 'functionResponse' in part:
                    logger.info(f"  Part[{j}] (functionResponse): {part['functionResponse'].get('name', 'unknown')}")
            logger.info("-"*80)
        
        # 记录工具定义
        if 'tools' in gemini_payload:
            tools_info = gemini_payload['tools']
            func_count = len(tools_info[0].get('functionDeclarations', [])) if tools_info else 0
            logger.info(f"Gemini API tools: {func_count} functions")
            for i, func in enumerate(tools_info[0].get('functionDeclarations', [])):
                logger.info(f"Gemini API tool[{i}]: {func.get('name', 'unknown')}")
        else:
            logger.info(f"Gemini API tools: None")
        
        # 记录完整 payload（截断）
        payload_str = json.dumps(gemini_payload, ensure_ascii=False, indent=2)
        logger.debug(f"Gemini API request payload (first 2000 chars):\n{payload_str[:2000]}")

        try:
            response = requests.post(
                url,
                headers=headers,
                json=gemini_payload,
                timeout=360
            )
            
            logger.info(f"Gemini API response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"Gemini API error: {response.status_code}")
                logger.error(f"Gemini API error response: {response.text}")
                response.raise_for_status()
            
            # 记录响应内容
            response_json = response.json()
            
            # 检查响应是否为空
            if not response_json:
                logger.error("Gemini API returned empty response (None)")
                raise Exception("Gemini API returned empty response")
            
            # 完整记录响应结构
            logger.info("="*80)
            logger.info("GEMINI API RESPONSE:")
            
            if response_json and 'candidates' in response_json:
                for i, candidate in enumerate(response_json['candidates']):
                    logger.info(f"Candidate[{i}]:")
                    content = candidate.get('content') or {}
                    parts = content.get('parts') or []
                    logger.info(f"  Role: {content.get('role', 'unknown')}")
                    logger.info(f"  Parts count: {len(parts)}")
                    
                    for j, part in enumerate(parts):
                        if 'text' in part:
                            logger.info(f"  Part[{j}] (text, {len(part['text'])} chars):")
                            logger.info(f"{part['text']}")
                        elif 'functionCall' in part:
                            func_call = part['functionCall']
                            logger.info(f"  Part[{j}] (functionCall):")
                            logger.info(f"    Name: {func_call.get('name', 'unknown')}")
                            logger.info(f"    Args: {json.dumps(func_call.get('args', {}), ensure_ascii=False, indent=6)}")
                    
                    # 记录 finishReason
                    if 'finishReason' in candidate:
                        logger.info(f"  Finish reason: {candidate['finishReason']}")
            
            logger.info("-"*80)
            
            # 转换响应为标准格式
            converted_response = self._convert_gemini_response(
                response_json,
                auth_token=auth_token,
                vendor_id=vendor_id,
                model_id=model_id
            )
            
            # 记录转换后的响应
            if converted_response.choices:
                message = converted_response.choices[0].message
                logger.info(f"Converted response:")
                logger.info(f"  Content length: {len(message.content) if message.content else 0}")
                if message.content:
                    logger.info(f"  Content: {message.content}")
                logger.info(f"  Tool calls: {len(message.tool_calls) if message.tool_calls else 0}")
                if message.tool_calls:
                    for i, tc in enumerate(message.tool_calls):
                        logger.info(f"  Tool call[{i}]:")
                        logger.info(f"    ID: {tc.id}")
                        logger.info(f"    Name: {tc.function.name}")
                        logger.info(f"    Arguments: {tc.function.arguments}")
            
            return converted_response
            
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            raise

    def _analyze_token_usage(self, usage_metadata: Dict) -> Dict[str, int]:
        """
        分析 Gemini API 返回的 token 使用统计
        
        Args:
            usage_metadata: API 响应中的 usageMetadata 字段
            
        Returns:
            包含详细 token 统计的字典:
            - input_token: 实际输入消耗（包括用户输入、系统指令、工具定义等）
            - output_token: 模型输出消耗
            - cache_read_token: 缓存读取的 token 数
            - total_token: 总消耗
            - overhead_token: 系统开销（差异部分，计入输入）
        """
        prompt_tokens = usage_metadata.get("promptTokenCount", 0)
        completion_tokens = usage_metadata.get("candidatesTokenCount", 0)
        total_tokens = usage_metadata.get("totalTokenCount", 0)
        cached_tokens = usage_metadata.get("cachedContentTokenCount", 0)
        
        # 计算系统开销（差异部分）
        overhead_tokens = total_tokens - prompt_tokens - completion_tokens
        
        # 实际输入 token = 用户输入 + 系统开销
        input_tokens = prompt_tokens + overhead_tokens
        
        result = {
            "input_token": input_tokens,
            "output_token": completion_tokens,
            "cache_read_token": cached_tokens,
            "total_token": total_tokens,
            "overhead_token": overhead_tokens,
            # 保留原始数据供参考
            "raw_prompt_tokens": prompt_tokens,
            "raw_completion_tokens": completion_tokens
        }
        
        logger.info(f"Token usage analysis: input={input_tokens}, output={completion_tokens}, "
                       f"cache_read={cached_tokens}, overhead={overhead_tokens}, total={total_tokens}")
        
        return result
    
    def _convert_gemini_response(
        self, data: Dict, 
        auth_token: Optional[str] = None, 
        vendor_id: Optional[int] = None, 
        model_id: Optional[int] = None
    ) -> Any:
        """将 Gemini 响应转换为标准格式"""
        class Message:
            def __init__(self, content, tool_calls=None, thought_signature=None):
                self.content = content
                self.tool_calls = tool_calls
                self.thought_signature = thought_signature
        
        class Choice:
            def __init__(self, message):
                self.message = message
        
        class Response:
            def __init__(self, choices, usage=None):
                self.choices = choices
                self.usage = usage
        
        # 提取并分析 token 使用统计
        usage_metadata = data.get("usageMetadata", {})
        usage = self._analyze_token_usage(usage_metadata)

        if not data.get("candidates"):
            logger.warning("Gemini response has no candidates")
            return Response([Choice(Message(""))])
        
        candidate = data["candidates"][0]
        
        # 检查 finishReason
        finish_reason = candidate.get("finishReason")
        if finish_reason == "MAX_TOKENS":
            logger.warning("Gemini response finished due to MAX_TOKENS - response may be incomplete")
        
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        
        # 如果没有 parts 但有 finish_reason，记录警告
        if not parts and finish_reason:
            logger.warning(f"Gemini response has no parts, finish_reason: {finish_reason}")
        
        text_content = ""
        tool_calls = []
        
        for part in parts:
            if "text" in part:
                text_content += part["text"]
            elif "functionCall" in part:
                func_call = part["functionCall"]
                tool_call = type('obj', (object,), {
                    'id': f"call_{uuid.uuid4()}",
                    'type': 'function',
                    'function': type('obj', (object,), {
                        'name': func_call.get('name', ''),
                        'arguments': json.dumps(func_call.get('args', {}), ensure_ascii=False)
                    })()
                })()
                tool_calls.append(tool_call)
        
        message = Message(text_content, tool_calls if tool_calls else None)

        # 解构 usage 数据，方便后续记录与上报
        output_token = usage.get("output_token", 0)
        cache_read_token = usage.get("cache_read_token", 0)
        total_token = usage.get("total_token", 0)

        logger.info(f"Gemini usage: {usage}")
        logger.info(f"Gemini metadata - auth_token={auth_token}, vendor_id={vendor_id}, model_id={model_id}")
        headers = {'Authorization': f'Bearer {auth_token}'}
        # 发起请求，增加token日志
        success, log_message, response_data = make_perseids_request(
            endpoint='user/token_log',
            method='POST',
            headers=headers,
            data={
                "input_token": total_token-output_token,
                "output_token": output_token,
                "cache_creation": 0,
                "cache_read": cache_read_token,
                "model_id": model_id,
                "vendor_id":vendor_id
            }
        )

        if not success:
            logger.info(f"增加token日志失败: {log_message}")
        return Response([Choice(message)])


# 全局单例
_gemini_client = None

def get_gemini_client() -> GeminiClient:
    """获取 Gemini 客户端单例"""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = GeminiClient()
    return _gemini_client
