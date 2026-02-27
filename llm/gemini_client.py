"""
Gemini API 客户端 - 统一的 Gemini 原生 API 调用接口
供 PM Agent 和 Expert Agent 使用
"""
import os
import json
import uuid
import logging
import requests
from pathlib import Path
from typing import Dict, List, Any, Optional
from perseids_client import make_perseids_request
from config.config_util import get_config_value

# 导入日志函数
try:
    from chat_app import log_api_interaction
except ImportError:
    # 如果导入失败，定义一个简单的替代函数
    def log_api_interaction(message: str, data: Any = None):
        pass

from script_writer_core.log_utils import should_log_debug, should_log_info, truncate_log_content

# 配置 API 日志记录器
def setup_api_logger():
    """设置 API 日志记录器，输出到 logs/api.log"""
    api_logger = logging.getLogger('gemini_api')
    api_logger.setLevel(logging.DEBUG)
    
    # 如果已经有 handler，不重复添加
    if api_logger.handlers:
        return api_logger
    
    # 创建 logs 目录 - 使用绝对路径
    # 获取项目根目录 (agents 目录的上一级)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    log_dir = Path(project_root) / 'logs'
    
    # 打印日志路径以便调试
    print(f"Gemini API Logger initialized. Log file: {log_dir / 'api.log'}")
    
    log_dir.mkdir(exist_ok=True)
    
    # 创建文件 handler（无缓冲模式）
    file_handler = logging.FileHandler(log_dir / 'api.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # 创建格式化器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    # 添加 handler
    api_logger.addHandler(file_handler)
    
    # 设置为无缓冲模式 - 每次写入立即刷新到磁盘
    class FlushingHandler(logging.FileHandler):
        def emit(self, record):
            super().emit(record)
            self.flush()
    
    # 替换为无缓冲的handler
    api_logger.removeHandler(file_handler)
    flushing_handler = FlushingHandler(log_dir / 'api.log', encoding='utf-8')
    flushing_handler.setLevel(logging.DEBUG)
    flushing_handler.setFormatter(formatter)
    api_logger.addHandler(flushing_handler)
    
    return api_logger

# 初始化日志记录器
logger = logging.getLogger(__name__)
api_logger = setup_api_logger()

# 优先使用 jiekou 配置，如果没有则使用 google 配置
API_KEY = get_config_value('jiekou', 'api_key') or get_config_value('google', 'api_key', default='')
BASE_URL = get_config_value('jiekou', 'base_url') or get_config_value('google', 'gemini_base_url', default='')


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
                        
                        # 根据Gemini文档：
                        # - 顺序调用：每个步骤的第一个（也是唯一的）functionCall需要thought_signature
                        # - 并行调用：同一步骤中只有第一个functionCall需要thought_signature，后续的不需要
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
        auth_token: str = None,
        vendor_id: int = None,
        model_id: int = None,
        max_tokens: int = 65536
    ) -> Any:
        """
        调用 Gemini 原生 API
        
        Args:
            model: 模型名称（如 gemini-3-flash-preview）
            messages: OpenAI 格式的消息列表
            tools: 工具定义列表
            temperature: 温度参数
            max_tokens: 最大输出 token 数
            
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
        api_logger.info(f"Gemini API URL: {url}")
        api_logger.info(f"Gemini API model: {model_name}")
        api_logger.info(f"Gemini API contents count: {len(gemini_payload.get('contents', []))}")
        
        # 记录完整 payload 到文件，命令行只显示前500字符
        payload_str = json.dumps(gemini_payload, ensure_ascii=False, indent=2)
        api_logger.debug(f"Gemini API request payload:\n{payload_str}")
        if should_log_debug():
            print(f"[DEBUG] Gemini API request payload (first 500 chars):\n{payload_str[:500]}")

        try:
            response = requests.post(
                url,
                headers=headers,
                json=gemini_payload,
                timeout=240
            )
            
            api_logger.info(f"Gemini API response status: {response.status_code}")
            
            if response.status_code != 200:
                api_logger.error(f"Gemini API error: {response.status_code}")
                api_logger.error(f"Gemini API error response: {response.text}")
                response.raise_for_status()
            
            # 记录响应内容
            response_json = response.json()
            
            # 检查响应是否为空
            if not response_json:
                api_logger.error("Gemini API returned empty response (None)")
                raise Exception("Gemini API returned empty response")
            
            # 完整记录响应结构
            api_logger.info("="*80)
            api_logger.info("GEMINI API RESPONSE:")
            
            if response_json and 'candidates' in response_json:
                for i, candidate in enumerate(response_json['candidates']):
                    api_logger.info(f"Candidate[{i}]:")
                    content = candidate.get('content') or {}
                    parts = content.get('parts') or []
                    api_logger.info(f"  Role: {content.get('role', 'unknown')}")
                    api_logger.info(f"  Parts count: {len(parts)}")
                    
                    for j, part in enumerate(parts):
                        if 'text' in part:
                            api_logger.info(f"  Part[{j}] (text, {len(part['text'])} chars):")
                            api_logger.info(f"{part['text']}")
                        elif 'functionCall' in part:
                            func_call = part['functionCall']
                            api_logger.info(f"  Part[{j}] (functionCall):")
                            api_logger.info(f"    Name: {func_call.get('name', 'unknown')}")
                            api_logger.info(f"    Args: {json.dumps(func_call.get('args', {}), ensure_ascii=False, indent=6)}")
                    
                    # 记录 finishReason
                    if 'finishReason' in candidate:
                        api_logger.info(f"  Finish reason: {candidate['finishReason']}")
            
            api_logger.info("-"*80)
            
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
                api_logger.debug(f"Converted response - Content length: {len(message.content) if message.content else 0}")
                api_logger.debug(f"Converted response - Tool calls: {len(message.tool_calls) if message.tool_calls else 0}")
            
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
        
        api_logger.info(f"Token usage analysis: input={input_tokens}, output={completion_tokens}, "
                       f"cache_read={cached_tokens}, overhead={overhead_tokens}, total={total_tokens}")
        
        return result

    def _convert_gemini_response(
        self,
        data: Dict,
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
            api_logger.info(f"Gemini usage1: {usage}")
            return Response([Choice(Message(""))], usage=usage)

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
        thought_signature = None
        
        for part in parts:
            if "text" in part:
                text_content += part["text"]
            elif "functionCall" in part:
                func_call = part["functionCall"]
                
                # 提取 thoughtSignature（如果存在）
                if "thoughtSignature" in part:
                    thought_signature = part["thoughtSignature"]
                    if should_log_debug():
                        api_logger.debug(f"Extracted thought_signature from response: {thought_signature[:100]}...")
                
                tool_call = type('obj', (object,), {
                    'id': f"call_{uuid.uuid4()}",
                    'type': 'function',
                    'function': type('obj', (object,), {
                        'name': func_call.get('name', ''),
                        'arguments': json.dumps(func_call.get('args', {}), ensure_ascii=False)
                    })()
                })()
                tool_calls.append(tool_call)
        
        message = Message(text_content, tool_calls if tool_calls else None, thought_signature)

        # 解构 usage 数据，方便后续记录与上报
        output_token = usage.get("output_token", 0)
        cache_read_token = usage.get("cache_read_token", 0)
        total_token = usage.get("total_token", 0)

        api_logger.info(f"Gemini usage: {usage}")
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
        return Response([Choice(message)], usage=usage)


# 全局单例
_gemini_client = None

def get_gemini_client() -> GeminiClient:
    """获取 Gemini 客户端单例"""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = GeminiClient()
    return _gemini_client
