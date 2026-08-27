"""
vLLM 本地推理服务 LLM 客户端
使用 vLLM 的 OpenAI 兼容端点 /v1/chat/completions

vLLM 服务由部署侧外部拉起（docker / systemd / vllm serve），本客户端仅负责调用。
部署侧必须通过 --served-model-name 使 API 模型名与数据库 model_name 一致（如 qwen3.8:27b），
完整部署说明见 docs/backend/vllm_local_model.md。

默认采样参数对齐 Qwen3.8 官方思考模式推荐值
（https://huggingface.co/Qwen/Qwen3.8-27B）：
temperature=1.0, top_p=0.95, top_k=20, min_p=0,
presence_penalty=0, repetition_penalty=1, enable_thinking=true
"""
import json
import logging
from typing import Dict, List, Any, Optional
from openai import OpenAI
from config.config_util import get_dynamic_config_value
from .base_llm_client import BaseLLMClient
from script_writer_core.log_utils import should_log_debug, truncate_log_content

logger = logging.getLogger(__name__)


def _get_llm_logger():
    """获取 LLM 日志记录器"""
    from .gemini_client import llm_logger
    return llm_logger


class VLLMClient(BaseLLMClient):
    """vLLM 本地推理服务 LLM 客户端（OpenAI 兼容）"""

    def __init__(self):
        """初始化 vLLM 客户端"""
        self._refresh_config()

    def _refresh_config(self):
        """刷新配置（从数据库动态读取）"""
        self.enabled = get_dynamic_config_value('llm', 'vllm', 'enabled', default=False)
        # 主服务默认端口为 8000（server.port），vLLM 默认也用 8000，故默认错开到 8001
        self.base_url = get_dynamic_config_value('llm', 'vllm', 'base_url', default='http://localhost:8001')
        # 模型参数配置（默认值对齐 Qwen3.8 官方思考模式推荐）
        self.temperature = get_dynamic_config_value('llm', 'vllm', 'temperature', default=1.0)
        self.top_p = get_dynamic_config_value('llm', 'vllm', 'top_p', default=0.95)
        self.top_k = get_dynamic_config_value('llm', 'vllm', 'top_k', default=20)
        self.min_p = get_dynamic_config_value('llm', 'vllm', 'min_p', default=0.0)
        self.presence_penalty = get_dynamic_config_value('llm', 'vllm', 'presence_penalty', default=0.0)
        self.repetition_penalty = get_dynamic_config_value('llm', 'vllm', 'repetition_penalty', default=1.0)
        self.enable_thinking = get_dynamic_config_value('llm', 'vllm', 'enable_thinking', default=True)

        if self.enabled:
            logger.info(f"VLLMClient config loaded: base_url={self.base_url}, temp={self.temperature}, top_p={self.top_p}")
        else:
            logger.debug("vLLM is disabled")

    def call_api(
        self,
        model: str,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 65536,
        auth_token: str = None,
        vendor_id: int = None,
        model_id: int = None,
        enable_thinking: Optional[bool] = None,
        thinking_effort: str = "medium",
        agent_id: Optional[str] = None,
        agent_scope: Optional[str] = None,
        request_timeout: Optional[float] = None,
    ) -> Any:
        """
        调用 vLLM 本地推理服务 API

        Args:
            model: 模型名称（如 vllm:qwen3.8:27b）
            messages: OpenAI 格式的消息列表
            tools: 工具定义列表（OpenAI function calling 格式）
            temperature: 温度参数（配置缺失时的 fallback）
            max_tokens: 最大输出 token 数
            auth_token: 认证 token（本地模型无鉴权，仅用于记录用量）
            vendor_id: 供应商 ID
            model_id: 模型 ID
            enable_thinking: 是否开启思考模式；None 时回退到全局配置 llm.vllm.enable_thinking，
                显式传入 True/False 则覆盖全局配置
            thinking_effort: 思考强度（low/medium/high/xhigh，high 映射为 Qwen3.8 的 xhigh）
            request_timeout: 单次请求 HTTP 超时（秒），None 时用 client 默认值

        Returns:
            Response 对象
        """
        if not self.enabled:
            raise Exception("vLLM 未启用，请在配置中设置 llm.vllm.enabled = true")

        # 处理模型名称：移除 "vllm:" 前缀
        actual_model = model
        if model.lower().startswith("vllm:"):
            actual_model = model[5:]  # 移除 "vllm:" 前缀

        try:
            # 统一底层 HTTP 超时（与 openai_base_client 一致）：
            # 否则 TCP 连接建立后等待响应体时会永久挂起
            try:
                from config.constant import ScriptSplitConstants
                http_timeout = ScriptSplitConstants.LLM_HTTP_TIMEOUT_SECONDS
            except Exception:
                http_timeout = 300
            # vLLM 不需要真正的 API key，但 OpenAI 库需要一个值
            client = OpenAI(
                api_key="vllm",
                base_url=f"{self.base_url}/v1",
                timeout=http_timeout,
            )

            # 使用配置的参数，调用方传入的 temperature 仅作为 fallback
            actual_temperature = self.temperature if self.temperature is not None else temperature

            kwargs = {
                "model": actual_model,
                "messages": messages,
                "temperature": actual_temperature,
                "top_p": self.top_p,
                "presence_penalty": self.presence_penalty,
            }

            # 单次请求超时：优先用调用方传入的 request_timeout，覆盖 client 默认值
            if request_timeout is not None:
                kwargs["timeout"] = request_timeout

            # vLLM 特有采样参数 + Qwen3 思考开关通过 extra_body 传递
            extra_body = {}
            if self.top_k is not None and self.top_k > 0:
                extra_body["top_k"] = self.top_k
            if self.min_p is not None and self.min_p > 0:
                extra_body["min_p"] = self.min_p
            if self.repetition_penalty is not None and self.repetition_penalty > 0:
                extra_body["repetition_penalty"] = self.repetition_penalty
            # 思维链配置：显式传入 enable_thinking（True/False）时覆盖全局配置，
            # None 时回退到全局配置 llm.vllm.enable_thinking
            actual_thinking = bool(self.enable_thinking if enable_thinking is None else enable_thinking)
            chat_template_kwargs = {"enable_thinking": actual_thinking}
            if actual_thinking:
                # Qwen3.8 支持 reasoning_effort（low/medium/xhigh）；
                # 前端 "high" 映射为 "xhigh"（见 LLMModel.QWEN_REASONING_EFFORT_MAP）
                from config.constant import LLMModel
                chat_template_kwargs["reasoning_effort"] = LLMModel.QWEN_REASONING_EFFORT_MAP.get(
                    thinking_effort, 'medium')
            extra_body["chat_template_kwargs"] = chat_template_kwargs
            kwargs["extra_body"] = extra_body

            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            # 如果有 tools，添加 function calling 支持
            if tools:
                functions = []
                for tool in tools:
                    if tool.get("type") == "function":
                        func = tool["function"]
                        functions.append({
                            "name": func["name"],
                            "description": func.get("description", ""),
                            "parameters": func.get("parameters", {})
                        })
                if functions:
                    kwargs["tools"] = [{"type": "function", "function": f} for f in functions]

            llm_logger = _get_llm_logger()
            llm_logger.info("="*80)
            llm_logger.info(f"VLLM API REQUEST:")
            llm_logger.info(f"  Model: {actual_model}")
            llm_logger.info(f"  Base URL: {self.base_url}")
            llm_logger.info(f"  Messages count: {len(messages)}")
            self._log_request_context(llm_logger, agent_id, agent_scope)
            llm_logger.info(f"  Temperature: {actual_temperature}, top_p={self.top_p}, top_k={self.top_k}")
            llm_logger.info(f"  presence_penalty: {self.presence_penalty}, repetition_penalty={self.repetition_penalty}")
            llm_logger.info(f"  enable_thinking: {actual_thinking}")
            llm_logger.info(f"  Max tokens: {max_tokens}")
            if tools:
                llm_logger.info(f"  Tools count: {len(tools)}")

            if should_log_debug():
                payload_str = json.dumps(kwargs, ensure_ascii=False, indent=2, default=str)
                llm_logger.debug(f"vLLM API request payload:\n{payload_str}")

            logger.info(f"vLLM API request: model={actual_model}, messages_count={len(messages)}")

            completion = client.chat.completions.create(**kwargs)

            # 提取响应内容
            choice = completion.choices[0]
            message = choice.message
            finish_reason = getattr(choice, 'finish_reason', None)

            # 处理 tool_calls
            tool_calls = None
            if hasattr(message, 'tool_calls') and message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    tool_call = type('obj', (object,), {
                        'id': tc.id,
                        'type': 'function',
                        'function': type('obj', (object,), {
                            'name': tc.function.name,
                            'arguments': tc.function.arguments
                        })()
                    })()
                    tool_calls.append(tool_call)

            content = message.content or ""
            reasoning_content = getattr(message, 'reasoning_content', None)

            # 提取 token 使用量（vLLM 返回标准 OpenAI usage；
            # 开启 prefix caching 时 cached tokens 位于 prompt_tokens_details.cached_tokens）
            usage_info = {"input_token": 0, "output_token": 0, "total_token": 0, "cache_read_token": 0}
            if hasattr(completion, 'usage') and completion.usage:
                usage_info = {
                    "input_token": getattr(completion.usage, 'prompt_tokens', 0) or 0,
                    "output_token": getattr(completion.usage, 'completion_tokens', 0) or 0,
                    "total_token": getattr(completion.usage, 'total_tokens', 0) or 0,
                    "cache_read_token": 0,
                }
                prompt_details = getattr(completion.usage, 'prompt_tokens_details', None)
                if prompt_details is not None:
                    usage_info["cache_read_token"] = getattr(prompt_details, 'cached_tokens', 0) or 0

            logger.info(f"vLLM API response: content_length={len(content)}, tool_calls={len(tool_calls) if tool_calls else 0}")

            llm_logger.info("="*80)
            llm_logger.info("VLLM API RESPONSE:")
            llm_logger.info(f"  Content length: {len(content)} chars")
            if content:
                llm_logger.info(f"  Content:\n{content}")
            if reasoning_content:
                llm_logger.info(f"  Reasoning content length: {len(reasoning_content)} chars")
                llm_logger.info(f"  Reasoning content:\n{truncate_log_content(reasoning_content)}")
            if tool_calls:
                llm_logger.info(f"  Tool calls count: {len(tool_calls)}")
                for i, tc in enumerate(tool_calls):
                    llm_logger.info(f"    Tool[{i}]: {tc.function.name}")
                    llm_logger.info(f"      Args: {tc.function.arguments}")
            llm_logger.info(f"  Token usage: {usage_info}")
            llm_logger.info("-"*80)

            # 记录 token 使用情况（本地模型也记录统计数据用于算力扣减）
            if auth_token and model_id:
                self._log_token_usage(usage_info, auth_token, vendor_id, model_id)

            return self._create_response(content, tool_calls, usage_info, reasoning_content, finish_reason)

        except Exception as e:
            logger.error(f"vLLM API call failed: {e}")
            raise


# 全局单例
_vllm_client = None


def get_vllm_client() -> VLLMClient:
    """获取 vLLM 客户端单例（每次调用时刷新配置）"""
    global _vllm_client
    if _vllm_client is None:
        _vllm_client = VLLMClient()
    else:
        _vllm_client._refresh_config()
    return _vllm_client
