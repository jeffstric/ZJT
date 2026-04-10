"""
Gemini API 客户端 - Gemini 原生 API 调用接口
继承自 BaseLLMClient
"""
import os
import json
import uuid
import logging
import requests
from pathlib import Path
from typing import Dict, List, Any, Optional
from perseids_server.client import make_perseids_request
from config.config_util import get_dynamic_config_value
from config.constant import GEMINI_URL_FORMATS
from .base_llm_client import BaseLLMClient

# 导入日志函数
try:
    from chat_app import log_api_interaction
except ImportError:
    def log_api_interaction(message: str, data: Any = None):
        pass

from script_writer_core.log_utils import should_log_debug, should_log_info, truncate_log_content

# 配置 LLM 日志记录器
def setup_llm_logger():
    """设置 LLM 日志记录器，输出到 logs/llm.{date}.log"""
    from utils.logger_config import DailyFileHandler

    llm_logger = logging.getLogger('llm')
    llm_logger.setLevel(logging.DEBUG)

    if llm_logger.handlers:
        return llm_logger

    class FlushingDailyHandler(DailyFileHandler):
        def emit(self, record):
            super().emit(record)
            if self.stream:
                self.stream.flush()

    file_handler = FlushingDailyHandler('llm', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    llm_logger.addHandler(file_handler)

    return llm_logger

logger = logging.getLogger(__name__)
llm_logger = setup_llm_logger()


def _mask_api_key(api_key: str) -> str:
    """对 API 密钥进行掩码处理"""
    if not api_key or len(api_key) < 8:
        return "***"
    return f"{api_key[:4]}...{api_key[-4:]}"


class GeminiClient(BaseLLMClient):
    """Gemini 原生 API 客户端"""

    # 类级别缓存: {base_url: "proxy" | "official"}
    _url_format_cache: Dict[str, str] = {}

    def __init__(self):
        """初始化 Gemini 客户端"""
        self._refresh_config()

    def _refresh_config(self):
        """刷新配置（从数据库动态读取）"""
        old_base_url = getattr(self, 'base_url', None)

        self.api_key = get_dynamic_config_value('llm', 'google', 'api_key', default='')
        self.base_url = get_dynamic_config_value('llm', 'google', 'gemini_base_url', default='')

        if not self.api_key or not self.base_url:
            logger.warning("Gemini API Key 或 Base URL 未配置")
        else:
            logger.info(f"GeminiClient config loaded: base_url={self.base_url}")

        if old_base_url and old_base_url != self.base_url:
            GeminiClient._url_format_cache.pop(old_base_url, None)
            logger.info(f"GeminiClient base_url changed, cleared cache for {old_base_url}")

    @classmethod
    def clear_url_format_cache(cls):
        """清除 URL 格式缓存（配置变更后调用）"""
        cls._url_format_cache.clear()
        logger.info("GeminiClient URL format cache cleared")

    def _build_url(self, model: str) -> str:
        """构建 Gemini API URL，支持两种格式自动探测和缓存"""
        base_url = self.base_url.rstrip('/')
        if base_url.endswith('/openai'):
            base_url = base_url[:-7]

        model_name = model.replace("gemini/", "", 1) if "/" in model else model

        if base_url in GeminiClient._url_format_cache:
            fmt = GeminiClient._url_format_cache[base_url]
            url = f"{base_url}{GEMINI_URL_FORMATS[fmt].format(model=model_name)}"
            llm_logger.debug(f"Gemini URL using cached format '{fmt}': {url}")
            return url

        for fmt_name, fmt_path in GEMINI_URL_FORMATS.items():
            url = f"{base_url}{fmt_path.format(model=model_name)}"
            if self._probe_url_format(url):
                GeminiClient._url_format_cache[base_url] = fmt_name
                llm_logger.info(f"Gemini URL format detected: '{fmt_name}' for base_url: {base_url}")
                return url

        default_fmt = "proxy"
        url = f"{base_url}{GEMINI_URL_FORMATS[default_fmt].format(model=model_name)}"
        llm_logger.warning(f"Gemini URL format probe failed, using default '{default_fmt}': {url}")
        return url

    def _probe_url_format(self, url: str) -> bool:
        """轻量级探测 URL 格式是否有效"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        test_payload = {
            "contents": [{"role": "user", "parts": [{"text": "Hi"}]}],
            "generationConfig": {"maxOutputTokens": 1}
        }

        try:
            response = requests.post(url, headers=headers, json=test_payload, timeout=10)

            if response.status_code == 404:
                llm_logger.debug(f"URL format probe failed (404): {url}")
                return False

            if response.status_code in [401, 403]:
                llm_logger.debug(f"URL format probe success (auth error): {url} -> {response.status_code}")
                return True

            if response.status_code == 200:
                try:
                    resp_json = response.json()
                    if "candidates" in resp_json and resp_json["candidates"]:
                        llm_logger.debug(f"URL format probe success (valid response): {url}")
                        return True
                    else:
                        error_msg = resp_json.get("error", {}).get("message", "unknown")
                        llm_logger.debug(f"URL format probe failed (invalid response): {url} -> {error_msg}")
                        return False
                except Exception:
                    llm_logger.debug(f"URL format probe failed (parse error): {url}")
                    return False

            llm_logger.debug(f"URL format probe failed: {url} -> {response.status_code}")
            return False

        except requests.exceptions.Timeout:
            llm_logger.debug(f"URL format probe timeout: {url}")
            return False
        except Exception as e:
            llm_logger.debug(f"URL format probe error: {url} -> {e}")
            return False

    def _convert_to_gemini_format(self, messages, tools=None):
        """将OpenAI格式的消息转换为Gemini原生格式"""
        gemini_data = {
            "contents": [],
            "generationConfig": {}
        }

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

                        is_first_function = len(parts) == 0 or not any('functionCall' in part for part in parts)

                        if is_first_function:
                            signature_to_use = msg.get("thought_signature")

                            if not signature_to_use:
                                for prev_msg in reversed(messages):
                                    if prev_msg.get("role") == "assistant" and prev_msg.get("thought_signature"):
                                        signature_to_use = prev_msg["thought_signature"]
                                        log_api_interaction(f"[Gemini格式转换] 为第一个函数 {func['name']} 使用历史thought_signature")
                                        break

                            if signature_to_use:
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

                    if msg.get("thought_signature") and not msg.get("tool_calls") and msg.get("content"):
                        if parts and "text" in parts[0]:
                            parts[0]["thoughtSignature"] = msg["thought_signature"]
                            log_api_interaction("[Gemini格式转换] 为文本内容添加thought_signature")

                    gemini_data["contents"].append(gemini_content)
            elif role == "tool":
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
        auth_token: str = None,
        vendor_id: int = None,
        model_id: int = None
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
            Response 对象
        """
        if not self.api_key or not self.base_url:
            raise Exception("Gemini API Key 或 Base URL 未配置")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        gemini_payload = self._convert_to_gemini_format(messages, tools)
        gemini_payload["generationConfig"] = {
            "maxOutputTokens": max_tokens,
            "temperature": temperature
        }

        url = self._build_url(model)
        
        llm_logger.info("="*80)
        llm_logger.info("GEMINI API REQUEST:")
        llm_logger.info(f"  Model: {model}")
        llm_logger.info(f"  URL: {url}")
        llm_logger.info(f"  API Key: {_mask_api_key(self.api_key)}")
        llm_logger.info(f"  Contents count: {len(gemini_payload.get('contents', []))}")
        llm_logger.info(f"  Max tokens: {max_tokens}")
        if tools:
            llm_logger.info(f"  Tools count: {len(tools)}")

        payload_str = json.dumps(gemini_payload, ensure_ascii=False, indent=2)

        if should_log_debug():
            system_instruction = gemini_payload.get('systemInstruction', {})
            system_parts = system_instruction.get('parts', [])
            if system_parts:
                system_prompt_text = system_parts[0].get('text', '')
                llm_logger.info(f"="*80)
                llm_logger.info(f"[DEV DEBUG] SYSTEM PROMPT (技能内容检查):")
                llm_logger.info(f"="*80)
                llm_logger.info(f"{system_prompt_text}")
                llm_logger.info(f"="*80)
                llm_logger.info(f"[DEV DEBUG] System prompt length: {len(system_prompt_text)} chars")
                llm_logger.info(f"="*80)
            print(f"[DEBUG] Gemini API request payload (first 500 chars):\n{payload_str[:500]}")

        llm_logger.debug(f"Gemini API request payload:\n{payload_str}")

        try:
            response = requests.post(
                url,
                headers=headers,
                json=gemini_payload,
                timeout=300
            )

            llm_logger.info(f"Gemini API response status: {response.status_code}")

            if response.status_code != 200:
                llm_logger.error(f"Gemini API error: {response.status_code}")
                llm_logger.error(f"Gemini API error response: {response.text}")
                response.raise_for_status()

            response_json = response.json()

            if not response_json:
                llm_logger.error("Gemini API returned empty response (None)")
                raise Exception("Gemini API returned empty response")

            llm_logger.info("="*80)
            llm_logger.info("GEMINI API RESPONSE:")

            if response_json and 'candidates' in response_json:
                for i, candidate in enumerate(response_json['candidates']):
                    llm_logger.info(f"Candidate[{i}]:")
                    content = candidate.get('content') or {}
                    parts = content.get('parts') or []
                    llm_logger.info(f"  Role: {content.get('role', 'unknown')}")
                    llm_logger.info(f"  Parts count: {len(parts)}")

                    for j, part in enumerate(parts):
                        if 'text' in part:
                            llm_logger.info(f"  Part[{j}] (text, {len(part['text'])} chars):")
                            llm_logger.info(f"{part['text']}")
                        elif 'functionCall' in part:
                            func_call = part['functionCall']
                            llm_logger.info(f"  Part[{j}] (functionCall):")
                            llm_logger.info(f"    Name: {func_call.get('name', 'unknown')}")
                            llm_logger.info(f"    Args: {json.dumps(func_call.get('args', {}), ensure_ascii=False, indent=6)}")

                    if 'finishReason' in candidate:
                        llm_logger.info(f"  Finish reason: {candidate['finishReason']}")

            llm_logger.info("-"*80)

            converted_response = self._convert_gemini_response(
                response_json,
                auth_token=auth_token,
                vendor_id=vendor_id,
                model_id=model_id
            )

            if converted_response.choices:
                message = converted_response.choices[0].message
                llm_logger.debug(f"Converted response - Content length: {len(message.content) if message.content else 0}")
                llm_logger.debug(f"Converted response - Tool calls: {len(message.tool_calls) if message.tool_calls else 0}")

            return converted_response

        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            raise

    def _analyze_token_usage(self, usage_metadata: Dict) -> Dict[str, int]:
        """分析 Gemini API 返回的 token 使用统计"""
        prompt_tokens = usage_metadata.get("promptTokenCount", 0)
        completion_tokens = usage_metadata.get("candidatesTokenCount", 0)
        total_tokens = usage_metadata.get("totalTokenCount", 0)
        cached_tokens = usage_metadata.get("cachedContentTokenCount", 0)

        overhead_tokens = total_tokens - prompt_tokens - completion_tokens
        input_tokens = prompt_tokens + overhead_tokens

        result = {
            "input_token": input_tokens,
            "output_token": completion_tokens,
            "cache_read_token": cached_tokens,
            "total_token": total_tokens,
            "overhead_token": overhead_tokens,
            "raw_prompt_tokens": prompt_tokens,
            "raw_completion_tokens": completion_tokens
        }

        llm_logger.info(f"Token usage analysis: input={input_tokens}, output={completion_tokens}, "
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
        usage_metadata = data.get("usageMetadata", {})
        usage = self._analyze_token_usage(usage_metadata)

        if not data.get("candidates"):
            logger.warning("Gemini response has no candidates")
            llm_logger.info(f"Gemini usage1: {usage}")
            return self._create_response("", usage=usage)

        candidate = data["candidates"][0]

        finish_reason = candidate.get("finishReason")
        if finish_reason == "MAX_TOKENS":
            logger.warning("Gemini response finished due to MAX_TOKENS - response may be incomplete")

        content = candidate.get("content") or {}
        parts = content.get("parts") or []

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

                if "thoughtSignature" in part:
                    thought_signature = part["thoughtSignature"]
                    if should_log_debug():
                        llm_logger.debug(f"Extracted thought_signature from response: {thought_signature[:100]}...")

                tool_call = type('obj', (object,), {
                    'id': f"call_{uuid.uuid4()}",
                    'type': 'function',
                    'function': type('obj', (object,), {
                        'name': func_call.get('name', ''),
                        'arguments': json.dumps(func_call.get('args', {}), ensure_ascii=False)
                    })()
                })()
                tool_calls.append(tool_call)

        message = self.Message(text_content, tool_calls if tool_calls else None, thought_signature)

        output_token = usage.get("output_token", 0)
        cache_read_token = usage.get("cache_read_token", 0)
        total_token = usage.get("total_token", 0)

        llm_logger.info(f"Gemini usage: {usage}")
        logger.info(f"Gemini metadata - auth_token={auth_token}, vendor_id={vendor_id}, model_id={model_id}")

        if auth_token and model_id:
            self._log_token_usage(usage, auth_token, vendor_id, model_id)

        return self.Response([self.Choice(message)], usage=usage)


# 全局单例
_gemini_client = None


def get_gemini_client() -> GeminiClient:
    """获取 Gemini 客户端单例（每次调用时刷新配置）"""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = GeminiClient()
    else:
        _gemini_client._refresh_config()
    return _gemini_client
