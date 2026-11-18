"""后台模块生成任务的 ask_user 适配器。

ExpertAgent 把注入对象当作 TaskManager 使用。本适配器把 verification
落到 agent-tasks JSON 事件流，不写 agent_verifications，也不接会话 SSE。

`AskUserMixin.wait_for_verification(..., timeout=300)` 的超时参数被忽略，
改用 `USER_MODULE_AGENT_TASK_QUESTION_TIMEOUT_SECONDS`。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from services.user_module_agent_service import UserModuleAgentService


logger = logging.getLogger(__name__)

LIMIT_QUESTION_ID = "q_limit"
CLOSED_QUESTION_ID = "q_closed"
QUESTION_EVENT_TYPE = "question"
ANSWER_EVENT_TYPE = "answer"
TIMEOUT_EVENT_TYPE = "question_timeout"
MAX_QUESTION_CHARS = 8000
MAX_TITLE_CHARS = 200
MAX_USER_INPUT_CHARS = 20000


@dataclass
class BackgroundVerification:
    """mixin 只读取 verification_id。"""

    verification_id: str
    task_id: str


def normalize_options(options: Optional[List[Any]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen = set()
    for item in options or []:
        if isinstance(item, dict):
            value = str(item.get("value") if item.get("value") is not None else item.get("label") or "").strip()
            label = str(item.get("label") or value).strip() or value
        else:
            value = str(item).strip()
            label = value
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append({"value": value, "label": label})
    return normalized


def assemble_user_input(
    *,
    options: Optional[List[Dict[str, str]]] = None,
    selected: Optional[str] = None,
    free_text: Optional[str] = None,
) -> str:
    parts: List[str] = []
    selected_value = str(selected or "").strip()
    if selected_value:
        label = selected_value
        for option in options or []:
            if str(option.get("value") or "") == selected_value:
                label = str(option.get("label") or selected_value)
                break
        parts.append(label)
    text = str(free_text or "").strip()
    if text:
        parts.append(text)
    return "\n".join(parts)[:MAX_USER_INPUT_CHARS]


def question_resolution(
    messages: Optional[List[Dict[str, Any]]],
    question_id: str,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """返回 (pending|answered|timeout|missing, 事件)。"""

    found_question = False
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        if str(message.get("question_id") or "") != str(question_id):
            continue
        event_type = str(message.get("type") or "")
        if event_type == QUESTION_EVENT_TYPE:
            found_question = True
            continue
        if not found_question:
            continue
        if event_type == ANSWER_EVENT_TYPE:
            return "answered", message
        if event_type == TIMEOUT_EVENT_TYPE:
            return "timeout", message
    if found_question:
        return "pending", None
    return "missing", None


class BackgroundAskUserAdapter:
    """以 task_manager 身份注入 ExpertAgent 的文件问答适配器。"""

    def __init__(self, service: "UserModuleAgentService", task_id: str):
        self._service = service
        self._task_id = str(task_id)

    def create_verification(
        self,
        task_id: str,
        verification_type: str,
        title: str,
        description: str,
        options: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> BackgroundVerification:
        del verification_type, context
        return self._service.create_ask_user_question(
            task_id or self._task_id,
            title=title,
            description=description,
            options=options,
        )

    def wait_for_verification(
        self,
        verification: BackgroundVerification,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        # mixin 写死 timeout=300；后台提问使用服务上的 1800s 常量。
        del timeout
        question_id = str(getattr(verification, "verification_id", "") or "")
        if question_id == LIMIT_QUESTION_ID:
            return {
                "success": False,
                "status": "limit",
                "error": (
                    "本任务 ask_user 已达上限，请立即停止提问，把剩余待确认事项写入结束总结。"
                ),
            }
        if question_id == CLOSED_QUESTION_ID:
            return {"success": False, "status": "cancelled", "error": "任务已结束"}
        return self._service.wait_for_ask_user_answer(
            self._task_id,
            question_id,
        )

    def push_message(self, task_id: str, message_type: str, data: Any) -> None:
        from services.user_module_agent_service import UserModuleAgentTaskNotFoundError

        try:
            self._service.append_progress_event(task_id or self._task_id, message_type, data)
        except UserModuleAgentTaskNotFoundError:
            return
        except Exception:
            logger.exception("写入模块生成进度事件失败 task_id=%s type=%s", task_id, message_type)

    def check_cancelled(self) -> None:
        """ExpertAgent 迭代检查点：管理员停止生成后尽快终止循环，避免继续消耗 LLM 调用。"""
        from services.user_module_agent_service import (
            UserModuleAgentTaskCancelledError,
        )

        if self._service.is_task_cancelled(self._task_id):
            logger.info("模块生成任务已取消，智能体在迭代检查点退出: task_id=%s", self._task_id)
            raise UserModuleAgentTaskCancelledError("管理员已停止生成")

    def get_power_confirm_state(self, session_key: str) -> Dict[str, Any]:
        del session_key
        return {"skip": True, "approved_ceiling": 0}

    def set_power_confirm_skip(self, session_key: str, skip: bool) -> None:
        del session_key, skip
        return None


def new_question_id() -> str:
    return f"q_{uuid.uuid4().hex}"
