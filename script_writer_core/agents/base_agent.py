from datetime import datetime
from typing import List, Dict, Any, Optional
import logging

from perseids_server.client import make_perseids_request
from config.unified_config import COMPUTING_POWER_CHECK_THRESHOLD

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependency
_conversation_recorder_cls = None

def _get_conversation_recorder():
    global _conversation_recorder_cls
    if _conversation_recorder_cls is None:
        from script_writer_core.conversation_recorder import ConversationRecorder
        _conversation_recorder_cls = ConversationRecorder
    return _conversation_recorder_cls


class InsufficientComputingPowerError(Exception):
    """算力不足异常 - 当用户算力降到阈值以下时抛出"""
    def __init__(self, computing_power: int, message: str = "算力不足，任务已停止"):
        self.computing_power = computing_power
        self.message = message
        super().__init__(self.message)


class PowerBudgetExhaustedError(InsufficientComputingPowerError):
    """单次任务算力消耗达到上限。

    继承 InsufficientComputingPowerError：PM/专家循环与 _execute_tool 中的
    「算力不足 → 截断历史 → 逐层上抛/推送停止消息」链路原样生效，任务优雅停止。
    """
    def __init__(self, consumed: int, limit: int):
        self.consumed = consumed
        self.limit = limit
        super().__init__(
            computing_power=0,
            message=(
                f"已达本次任务算力上限（本次未授权消耗 {consumed}，上限 {limit}），"
                f"任务已自动暂停；充值或调高上限后重新发送消息即可继续"
            ),
        )


def check_computing_power_sync(auth_token: str, agent_id: str, threshold: int = COMPUTING_POWER_CHECK_THRESHOLD) -> int:
    """
    同步检查用户算力（在后台线程中使用）

    Args:
        auth_token: 认证令牌
        agent_id: 调用方 agent ID（用于日志）
        threshold: 算力阈值，默认 1

    Returns:
        int: 当前算力值

    Raises:
        InsufficientComputingPowerError: 算力低于阈值
    """
    if not auth_token:
        return 999999  # 无 token 时跳过检查

    try:
        headers = {'Authorization': f'Bearer {auth_token}'}
        success, message, response_data = make_perseids_request(
            endpoint='user/check_computing_power',
            method='GET',
            headers=headers
        )

        if not success:
            logger.warning(f"{agent_id}: 算力检查失败: {message}, 继续执行")
            return 999999  # 检查失败时不阻断任务

        computing_power = response_data.get('computing_power', 0) if isinstance(response_data, dict) else 0

        if computing_power < threshold:
            raise InsufficientComputingPowerError(
                computing_power=computing_power,
                message=f"算力不足（当前: {computing_power}），任务已停止"
            )

        return computing_power

    except InsufficientComputingPowerError:
        raise
    except Exception as e:
        logger.warning(f"{agent_id}: 算力检查异常: {e}, 继续执行")
        return 999999  # 异常时不阻断任务


class BaseAgent:
    """智能体基类"""
    
    def __init__(
        self,
        agent_id: str,
        skill_names: List[str],
        model: str,
        allowed_tools: List[str],
        system_prompt: str
    ):
        self.agent_id = agent_id
        self.skill_names = skill_names
        # 保留 skill_name 用于向后兼容（使用第一个技能）
        self.skill_name = skill_names[0] if skill_names else "unknown"
        self.model = model
        self.allowed_tools = allowed_tools
        self.system_prompt = system_prompt
        self.conversation_history: List[Dict[str, Any]] = []
        self.created_at = datetime.now()

        # 双写相关属性（子类在 execute 时设置）
        self._session_id: Optional[str] = None
        self._task_id: Optional[str] = None
        self._conversation_recorder = None  # ConversationRecorder 实例
        self._agent_scope: str = "pm"  # 子类覆盖为 "expert"

        logger.info(f"Initialized {self.__class__.__name__} - ID: {agent_id}, Skills: {', '.join(skill_names)}")
    
    def send_message(self, message: str, **kwargs) -> Dict[str, Any]:
        """发送消息并获取响应"""
        raise NotImplementedError("Subclasses must implement send_message()")
    
    def handle_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """处理工具调用"""
        if tool_name not in self.allowed_tools:
            error_msg = f"工具 {tool_name} 不在允许列表中"
            logger.warning(f"{self.agent_id}: {error_msg}")
            return {"error": error_msg}
        
        return self._execute_tool(tool_name, tool_args)
    
    def _execute_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具调用 - 由子类实现具体逻辑"""
        raise NotImplementedError("Subclasses must implement _execute_tool()")
    
    def add_to_history(self, role: str, content: Any, extra_meta: Optional[Dict[str, Any]] = None):
        """添加消息到对话历史（内存 + DB 双写）"""
        logger.debug(f"{self.agent_id}: add_to_history called - role={role}, content type={type(content).__name__}")

        if role == "tool":
            logger.info(f"{self.agent_id}: Adding TOOL message to conversation_history:")
            logger.info(f"{self.agent_id}:   - content type: {type(content).__name__}")
            if isinstance(content, dict):
                logger.info(f"{self.agent_id}:   - content keys: {list(content.keys())}")
                logger.info(f"{self.agent_id}:   - content: {content}")
            else:
                logger.warning(f"{self.agent_id}:   - WARNING: content is not dict, it's {type(content).__name__}: {content}")

        # 内存写入（原有逻辑不变）
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

        logger.debug(f"{self.agent_id}: conversation_history now has {len(self.conversation_history)} messages")

        # DB 双写
        if self._conversation_recorder and self._session_id:
            try:
                metadata = self._extract_message_metadata(role, content)
                # 额外元数据（如 verification_id）覆盖
                if extra_meta:
                    metadata.update(extra_meta)

                # 自动检测 verification_answer：
                # 如果 role=="user" 且携带 verification_id，说明是用户回答验证问题
                # 自动设置 message_type 使幂等键与 API 路由一致
                db_content = content
                if role == "user" and metadata.get("verification_id") and metadata.get("message_type") == "normal":
                    metadata["message_type"] = "verification_answer"
                    # 规范化 content 为 {"text": ...} 格式，与 API 路径一致
                    if isinstance(content, str):
                        db_content = {"text": content}

                if self._agent_scope == "expert" and not (extra_meta and "visibility" in extra_meta):
                    metadata["visibility"] = self._get_expert_message_visibility(role, metadata)

                self._conversation_recorder.append_message(
                    session_id=self._session_id,
                    role=role,
                    content=db_content,
                    task_id=self._task_id,
                    agent_id=self.agent_id,
                    agent_scope=self._agent_scope,
                    source="agent",
                    **metadata
                )
            except Exception as e:
                logger.error(f"{self.agent_id}: Failed to persist message to DB: {e}")

    def _extract_message_metadata(self, role: str, content: Any) -> Dict[str, Any]:
        """从 role/content 中提取 DB 写入所需的元数据字段"""
        metadata = {"message_type": "normal", "visibility": "both"}

        if role == "system":
            metadata["message_type"] = "system_prompt"
            metadata["visibility"] = "llm"
        elif role == "verification":
            metadata["message_type"] = "verification_request"
            metadata["visibility"] = "ui"
            if isinstance(content, dict):
                metadata["verification_id"] = content.get("verification_id")
        elif role == "tool":
            metadata["message_type"] = "tool_result"
            if isinstance(content, dict):
                metadata["tool_call_id"] = content.get("tool_call_id")
                metadata["tool_name"] = content.get("name")
                metadata["provider_payload"] = {
                    "role": "tool",
                    "tool_call_id": content.get("tool_call_id", ""),
                    "content": content,
                }
        elif role == "assistant" and isinstance(content, dict) and "tool_calls" in content:
            metadata["message_type"] = "tool_call"
            metadata["provider_payload"] = {
                "role": "assistant",
                "content": content.get("text"),
                "tool_calls": content.get("tool_calls"),
            }
            if "thought_signature" in content:
                metadata["provider_payload"]["thought_signature"] = content["thought_signature"]
            if "reasoning_content" in content:
                metadata["provider_payload"]["reasoning_content"] = content["reasoning_content"]
        elif role == "assistant" and isinstance(content, dict) and "reasoning_content" in content:
            metadata["provider_payload"] = {
                "role": "assistant",
                "content": content.get("text", ""),
                "reasoning_content": content.get("reasoning_content", ""),
            }
        elif role == "summary":
            metadata["message_type"] = "context_summary"
            metadata["visibility"] = "llm"

        return metadata

    def _get_expert_message_visibility(self, role: str, metadata: Dict[str, Any]) -> str:
        """ExpertAgent messages keep internals hidden, but expose user-facing output."""
        message_type = metadata.get("message_type")

        if message_type == "verification_request":
            return "ui"
        if message_type == "verification_answer":
            return "both"
        if role == "assistant" and message_type == "normal":
            return "both"
        if role == "summary":
            return "llm"
        if role == "system":
            return "llm"
        return "internal"
    
    def clear_history(self):
        """清空对话历史"""
        self.conversation_history = []
        logger.info(f"{self.agent_id}: 对话历史已清空")
    
    def get_history_summary(self) -> str:
        """获取对话历史摘要"""
        return f"智能体: {self.agent_id}, 对话轮次: {len(self.conversation_history)}, 创建时间: {self.created_at}"
