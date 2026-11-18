"""管理员专用的用户模块代码生成智能体服务。

该服务绕过剧本 PM，固定运行 ``generate-user-api-module`` 专家。任务元数据使用
原子 JSON 持久化，便于多 Worker 查询；管理员令牌只保留在执行线程内，绝不落盘。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock, Timeout as FileLockTimeout

from config.constant import (
    USER_MODULE_AGENT_TASK_HEARTBEAT_INTERVAL_SECONDS,
    USER_MODULE_AGENT_TASK_MAX_CONCURRENCY,
    USER_MODULE_AGENT_TASK_MAX_PROGRESS_EVENTS,
    USER_MODULE_AGENT_TASK_MAX_QUESTIONS,
    USER_MODULE_AGENT_TASK_MAX_QUESTIONS_COMFYUI,
    USER_MODULE_AGENT_TASK_PROGRESS_CONTENT_MAX_CHARS,
    USER_MODULE_AGENT_TASK_QUESTION_POLL_INTERVAL_SECONDS,
    USER_MODULE_AGENT_TASK_QUESTION_TIMEOUT_SECONDS,
    USER_MODULE_AGENT_TASK_RESULT_MAX_CHARS,
    USER_MODULE_AGENT_TASK_STATE_LOCK_TIMEOUT_SECONDS,
    USER_MODULE_AGENT_TASK_STALE_TIMEOUT_SECONDS,
    USER_MODULE_AGENT_TASK_WALL_CLOCK_TIMEOUT_SECONDS,
    USER_MODULE_COMFYUI_CONNECTOR,
    USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
    USER_MODULE_GENERATION_MAX_FILE_BYTES,
    USER_MODULE_HTTP_CONNECTOR,
)
from module_runtime.comfyui import ComfyUIError, host_port_from_base_url, normalize_base_url
from module_runtime.generation import AsyncGenerationService
from module_runtime.paths import atomic_write_json, ensure_user_module_layout, resolve_within_root


logger = logging.getLogger(__name__)
USER_MODULE_AGENT_NAME = "generate-user-api-module"
DEFAULT_COMFYUI_REQUIREMENT = (
    "对接本地 ComfyUI 工作流。地址与 API JSON 已由系统写入 vendor/comfyui.json 与 "
    "vendor/workflow.json。请按 Skill 的本地 ComfyUI 分支生成模块：把地址写入 "
    "src/settings.py，工作流转成 src/workflow_graph.py，推断节点映射，"
    "completion_modes 只声明 polling，不要询问 ComfyUI 地址或 webhook。"
)


def load_comfyui_workflow_text(
    *,
    workflow_json: Optional[str] = None,
    workflow_path: Optional[str] = None,
) -> str:
    """读取管理员提供的 ComfyUI API JSON 文本（核心侧，不是模块代码）。"""

    raw = str(workflow_json or "").strip()
    path_value = str(workflow_path or "").strip()
    if path_value:
        candidate = Path(path_value)
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("工作流路径必须是普通文件")
        size = candidate.stat().st_size
        if size > USER_MODULE_GENERATION_MAX_FILE_BYTES:
            raise ValueError("工作流 JSON 超过大小限制")
        raw = candidate.read_text(encoding="utf-8")
    if not raw:
        raise ValueError("缺少 ComfyUI 工作流 JSON")
    if len(raw.encode("utf-8")) > USER_MODULE_GENERATION_MAX_FILE_BYTES:
        raise ValueError("工作流 JSON 超过大小限制")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"工作流不是合法 JSON: {exc}") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("工作流 JSON 必须是非空对象")
    return json.dumps(parsed, ensure_ascii=False, indent=2)
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
RECOVERY_POLICY = "fail_on_stale_heartbeat"
PROGRESS_EVENT_TYPES = frozenset({"tool_call", "tool_result", "progress", "message", "status"})
STATUS_EVENT_CONTENT = {
    "queued": "模块生成任务已进入队列",
    "running": "模块生成智能体已开始读取协议并编写草稿",
    "completed": "模块草稿已生成并通过校验，等待管理员审查",
    "failed": "模块生成任务失败",
    "cancelled": "模块生成任务已被管理员停止",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserModuleAgentTaskNotFoundError(LookupError):
    pass


class UserModuleAgentBusyError(RuntimeError):
    pass


class UserModuleAgentCreateError(ValueError):
    """创建模块生成任务时的可映射 HTTP 错误。"""

    def __init__(self, message: str, *, code: str = "invalid_module_agent_input", status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class UserModuleAgentAnswerError(ValueError):
    """管理员提交问答时的可映射 HTTP 错误。"""

    def __init__(self, message: str, *, code: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class UserModuleAgentTaskCancelledError(RuntimeError):
    """管理员已停止生成；由执行线程在迭代检查点感知并抛出，使智能体循环尽快退出。"""


class WallClockGuard:
    """可暂停的墙钟预算。提问等待期间 pause，避免把管理员思考算进 LLM hang。"""

    def __init__(self, timeout_seconds: float, on_timeout) -> None:
        self._lock = threading.Lock()
        self._remaining = max(0.05, float(timeout_seconds))
        self._on_timeout = on_timeout
        self._timer: Optional[threading.Timer] = None
        self._running_since: Optional[float] = None
        self._paused = True
        self._fired = False
        self._cancelled = False

    def start(self) -> None:
        self.resume()

    def pause(self) -> None:
        should_fire = False
        with self._lock:
            if self._cancelled or self._fired or self._paused:
                return
            elapsed = time.monotonic() - (self._running_since or time.monotonic())
            self._remaining = max(0.0, self._remaining - elapsed)
            self._paused = True
            self._running_since = None
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._remaining <= 0:
                self._fired = True
                should_fire = True
        if should_fire:
            self._on_timeout()

    def resume(self) -> None:
        should_fire = False
        with self._lock:
            if self._cancelled or self._fired or not self._paused:
                return
            if self._remaining <= 0:
                self._fired = True
                should_fire = True
            else:
                self._paused = False
                self._running_since = time.monotonic()
                timer = threading.Timer(self._remaining, self._fire)
                timer.daemon = True
                timer.name = "user-module-agent-wallclock"
                self._timer = timer
                timer.start()
        if should_fire:
            self._on_timeout()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._running_since = None
            self._paused = True

    def _fire(self) -> None:
        with self._lock:
            if self._cancelled or self._fired:
                return
            self._fired = True
            self._timer = None
            self._running_since = None
            self._paused = True
        self._on_timeout()


class UserModuleAgentService:
    """创建、运行和查询专用模块生成任务。"""

    def __init__(
        self,
        *,
        module_root: Optional[Path] = None,
        generation_service: Optional[AsyncGenerationService] = None,
        agents_config_path: Optional[Path] = None,
        max_concurrency: int = USER_MODULE_AGENT_TASK_MAX_CONCURRENCY,
        heartbeat_interval_seconds: float = USER_MODULE_AGENT_TASK_HEARTBEAT_INTERVAL_SECONDS,
        stale_timeout_seconds: float = USER_MODULE_AGENT_TASK_STALE_TIMEOUT_SECONDS,
        state_lock_timeout_seconds: float = USER_MODULE_AGENT_TASK_STATE_LOCK_TIMEOUT_SECONDS,
        wall_clock_timeout_seconds: float = USER_MODULE_AGENT_TASK_WALL_CLOCK_TIMEOUT_SECONDS,
        question_timeout_seconds: float = USER_MODULE_AGENT_TASK_QUESTION_TIMEOUT_SECONDS,
        max_questions: int = USER_MODULE_AGENT_TASK_MAX_QUESTIONS,
        question_poll_interval_seconds: float = USER_MODULE_AGENT_TASK_QUESTION_POLL_INTERVAL_SECONDS,
        max_progress_events: int = USER_MODULE_AGENT_TASK_MAX_PROGRESS_EVENTS,
        progress_content_max_chars: int = USER_MODULE_AGENT_TASK_PROGRESS_CONTENT_MAX_CHARS,
    ):
        self.module_root = ensure_user_module_layout(module_root)
        self.task_root = resolve_within_root(self.module_root, "state", "agent-tasks")
        self.task_root.mkdir(parents=True, exist_ok=True)
        self.execution_slot_root = resolve_within_root(self.task_root, "execution-slots")
        self.execution_slot_root.mkdir(parents=True, exist_ok=True)
        self.generation_service = generation_service or AsyncGenerationService()
        # agents_config.json 属主仓 script_writer_core 配置（expert 定义随主仓），
        # 本文件位于主仓 services/，主仓根是 parents[1]
        self.agents_config_path = Path(
            agents_config_path
            or Path(__file__).resolve().parents[1]
            / "script_writer_core"
            / "config"
            / "agents_config.json"
        )
        self._threads: Dict[str, threading.Thread] = {}
        self._threads_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_count = 0
        self.max_concurrency = max(1, int(max_concurrency))
        self.heartbeat_interval_seconds = max(0.1, float(heartbeat_interval_seconds))
        self.stale_timeout_seconds = max(
            self.heartbeat_interval_seconds * 2,
            float(stale_timeout_seconds),
        )
        self.state_lock_timeout_seconds = max(0.5, float(state_lock_timeout_seconds))
        # 单次任务的挂钟时间上限：LLM hang 时心跳仍会刷新、计数型限制无法兜底，
        # 必须有挂钟 deadline 强制置失败释放执行槽（见 review.md M4）。
        self.wall_clock_timeout_seconds = max(
            float(stale_timeout_seconds) * 2,
            float(wall_clock_timeout_seconds),
        )
        self.question_timeout_seconds = max(0.05, float(question_timeout_seconds))
        self.max_questions = max(1, int(max_questions))
        self.question_poll_interval_seconds = max(0.05, float(question_poll_interval_seconds))
        self.max_progress_events = max(1, int(max_progress_events))
        self.progress_content_max_chars = max(32, int(progress_content_max_chars))
        self._wall_clock_guards: Dict[str, WallClockGuard] = {}
        self.worker_instance_id = str(uuid.uuid4())

    def _acquire_execution_slot(self) -> FileLock:
        with self._threads_lock:
            if self._active_count >= self.max_concurrency:
                raise UserModuleAgentBusyError(
                    f"模块生成智能体正忙（并发上限 {self.max_concurrency}），请稍后重试"
                )
            acquired_lock: Optional[FileLock] = None
            for index in range(self.max_concurrency):
                candidate = FileLock(
                    str(self.execution_slot_root / f"slot-{index}.lock"),
                    timeout=0,
                    thread_local=False,
                )
                try:
                    candidate.acquire()
                    acquired_lock = candidate
                    break
                except FileLockTimeout:
                    continue
            if acquired_lock is None:
                raise UserModuleAgentBusyError(
                    f"模块生成智能体正忙（全局并发上限 {self.max_concurrency}），请稍后重试"
                )
            self._active_count += 1
            return acquired_lock

    def _release_execution_slot(self, execution_lock: Optional[FileLock]) -> None:
        if execution_lock is not None and execution_lock.is_locked:
            execution_lock.release()
        with self._threads_lock:
            self._active_count = max(0, self._active_count - 1)

    def _task_path(self, task_id: str) -> Path:
        try:
            parsed = str(uuid.UUID(str(task_id)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise UserModuleAgentTaskNotFoundError("模块生成任务不存在") from exc
        return resolve_within_root(self.task_root, f"{parsed}.json")

    def _read_task_sync(self, task_id: str) -> Dict[str, Any]:
        path = self._task_path(task_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UserModuleAgentTaskNotFoundError("模块生成任务不存在") from exc
        if not isinstance(payload, dict):
            raise UserModuleAgentTaskNotFoundError("模块生成任务不存在")
        return payload

    @contextmanager
    def _task_state_guard(self, task_id: str):
        """跨进程的短期文件锁，避免多 Worker 心跳与终态更新互相覆盖。"""

        normalized_task_id = str(uuid.UUID(str(task_id)))
        lock_path = resolve_within_root(self.task_root, f".{normalized_task_id}.lock")
        deadline = time.monotonic() + self.state_lock_timeout_seconds
        while True:
            try:
                with lock_path.open("x", encoding="ascii") as lock_file:
                    lock_file.write(f"{os.getpid()} {self.worker_instance_id}\n")
                break
            except FileExistsError:
                try:
                    if time.time() - lock_path.stat().st_mtime > self.state_lock_timeout_seconds * 2:
                        lock_path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError("模块生成任务状态正被另一个工作进程修改")
                time.sleep(0.025)
        try:
            yield
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    def _update_task_sync(self, task_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        with self._state_lock:
            with self._task_state_guard(task_id):
                state = self._read_task_sync(task_id)
                if state.get("status") in TERMINAL_STATUSES:
                    return state
                previous_status = state.get("status")
                state.update(changes)
                next_status = state.get("status")
                if next_status != previous_status and next_status in STATUS_EVENT_CONTENT:
                    messages = list(state.get("messages") or [])
                    content = STATUS_EVENT_CONTENT[next_status]
                    if next_status == "failed" and state.get("error"):
                        content = f"{content}：{str(state['error'])[:4000]}"
                    messages.append(
                        {
                            "id": int(state.get("next_message_id") or 1),
                            "type": next_status,
                            "content": content,
                            "created_at": _utc_now(),
                        }
                    )
                    state["messages"] = messages
                    state["next_message_id"] = messages[-1]["id"] + 1
                state["updated_at"] = _utc_now()
                atomic_write_json(self._task_path(task_id), state)
                return state

    def _heartbeat_task_sync(self, task_id: str) -> None:
        with self._state_lock:
            with self._task_state_guard(task_id):
                state = self._read_task_sync(task_id)
                if state.get("status") not in {"queued", "running"}:
                    return
                now = _utc_now()
                state["heartbeat_at"] = now
                state["updated_at"] = now
                atomic_write_json(self._task_path(task_id), state)

    def _heartbeat_loop(self, task_id: str, stop_event: threading.Event) -> None:
        while not stop_event.wait(self.heartbeat_interval_seconds):
            try:
                self._heartbeat_task_sync(task_id)
            except UserModuleAgentTaskNotFoundError:
                return
            except Exception:
                logger.exception("更新模块生成智能体任务心跳失败: task_id=%s", task_id)

    def pause_wall_clock(self, task_id: str) -> None:
        with self._threads_lock:
            guard = self._wall_clock_guards.get(str(task_id))
        if guard is not None:
            guard.pause()

    def resume_wall_clock(self, task_id: str) -> None:
        with self._threads_lock:
            guard = self._wall_clock_guards.get(str(task_id))
        if guard is not None:
            guard.resume()

    def _progress_event_content(self, event_type: str, data: Any) -> str:
        limit = self.progress_content_max_chars
        if isinstance(data, str):
            return data.strip()[:limit]
        if not isinstance(data, dict):
            return ""
        if event_type == "tool_call":
            names: List[str] = []
            for raw in list(data.get("tool_names") or [])[:8]:
                cleaned = "".join(
                    ch for ch in str(raw) if ch.isalnum() or ch in "._-"
                )[:64]
                if cleaned:
                    names.append(cleaned)
            if not names:
                return "正在调用工具"
            return ("正在调用 " + "、".join(names))[:limit]
        text = data.get("content") or data.get("message") or data.get("step") or ""
        return str(text).strip()[:limit]

    def append_progress_event(self, task_id: str, message_type: str, data: Any) -> None:
        event_type = str(message_type or "").strip()[:32]
        if event_type not in PROGRESS_EVENT_TYPES:
            return
        content = self._progress_event_content(event_type, data)
        if not content:
            return
        with self._state_lock:
            with self._task_state_guard(task_id):
                state = self._read_task_sync(task_id)
                if state.get("status") in TERMINAL_STATUSES:
                    return
                progress_count = sum(
                    1
                    for message in list(state.get("messages") or [])
                    if isinstance(message, dict) and message.get("type") in PROGRESS_EVENT_TYPES
                )
                if progress_count >= self.max_progress_events:
                    return
                self._append_event_unlocked(
                    state,
                    {
                        "type": event_type,
                        "content": content,
                    },
                )
                atomic_write_json(self._task_path(task_id), state)

    def _append_event_unlocked(self, state: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        messages = list(state.get("messages") or [])
        payload = dict(event)
        payload["id"] = int(state.get("next_message_id") or 1)
        payload.setdefault("created_at", _utc_now())
        messages.append(payload)
        state["messages"] = messages
        state["next_message_id"] = payload["id"] + 1
        state["updated_at"] = payload["created_at"]
        return payload

    def create_ask_user_question(
        self,
        task_id: str,
        *,
        title: str,
        description: str,
        options: Optional[List[Any]] = None,
    ):
        from services.user_module_ask_user_adapter import (
            CLOSED_QUESTION_ID,
            LIMIT_QUESTION_ID,
            MAX_QUESTION_CHARS,
            MAX_TITLE_CHARS,
            QUESTION_EVENT_TYPE,
            BackgroundVerification,
            new_question_id,
            normalize_options,
        )

        normalized_options = normalize_options(options)
        with self._state_lock:
            with self._task_state_guard(task_id):
                state = self._read_task_sync(task_id)
                if state.get("status") in TERMINAL_STATUSES:
                    logger.info("拒绝在终态任务上提问: task_id=%s", task_id)
                    return BackgroundVerification(CLOSED_QUESTION_ID, str(task_id))
                existing = sum(
                    1
                    for message in list(state.get("messages") or [])
                    if isinstance(message, dict) and message.get("type") == QUESTION_EVENT_TYPE
                )
                max_questions = max(1, int(state.get("max_questions") or self.max_questions))
                if existing >= max_questions:
                    logger.info("模块生成任务提问已达上限: task_id=%s count=%s", task_id, existing)
                    return BackgroundVerification(LIMIT_QUESTION_ID, str(task_id))
                question_id = new_question_id()
                now = _utc_now()
                deadline = (
                    datetime.now(timezone.utc) + timedelta(seconds=self.question_timeout_seconds)
                ).isoformat()
                question_text = str(description or "")[:MAX_QUESTION_CHARS]
                event = {
                    "type": QUESTION_EVENT_TYPE,
                    "question_id": question_id,
                    "title": str(title or "")[:MAX_TITLE_CHARS],
                    "question": question_text,
                    "content": question_text,
                    "options": normalized_options,
                    "allow_free_text": True,
                    "status": "pending",
                    "deadline_at": deadline,
                    "created_at": now,
                }
                self._append_event_unlocked(state, event)
                atomic_write_json(self._task_path(task_id), state)
                logger.info("模块生成任务发出提问: task_id=%s question_id=%s", task_id, question_id)
                return BackgroundVerification(question_id, str(task_id))

    def wait_for_ask_user_answer(self, task_id: str, question_id: str) -> Dict[str, Any]:
        from services.user_module_ask_user_adapter import (
            assemble_user_input,
            question_resolution,
        )

        deadline = time.monotonic() + self.question_timeout_seconds
        self.pause_wall_clock(task_id)
        try:
            while True:
                try:
                    self._heartbeat_task_sync(task_id)
                    state = self._read_task_sync(task_id)
                except UserModuleAgentTaskNotFoundError:
                    return {"success": False, "status": "cancelled", "error": "任务已结束"}
                if state.get("status") in TERMINAL_STATUSES:
                    return {"success": False, "status": "cancelled", "error": "任务已结束"}
                status, event = question_resolution(state.get("messages"), question_id)
                if status == "answered" and event is not None:
                    user_input = assemble_user_input(
                        options=self._question_options(state.get("messages"), question_id),
                        selected=event.get("selected"),
                        free_text=event.get("free_text"),
                    )
                    return {
                        "success": True,
                        "status": "approved",
                        "user_input": user_input,
                    }
                if status == "timeout":
                    return {"success": False, "status": "timeout", "error": "验证超时"}
                if status == "missing":
                    return {"success": False, "status": "cancelled", "error": "提问不存在"}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(self.question_poll_interval_seconds, remaining))

            self._append_question_timeout_sync(task_id, question_id)
            return {"success": False, "status": "timeout", "error": "验证超时"}
        finally:
            self.resume_wall_clock(task_id)

    def _question_options(self, messages: Optional[List[Any]], question_id: str) -> List[Dict[str, str]]:
        from services.user_module_ask_user_adapter import QUESTION_EVENT_TYPE

        for message in messages or []:
            if (
                isinstance(message, dict)
                and message.get("type") == QUESTION_EVENT_TYPE
                and str(message.get("question_id") or "") == str(question_id)
            ):
                return list(message.get("options") or [])
        return []

    def _append_question_timeout_sync(self, task_id: str, question_id: str) -> None:
        from services.user_module_ask_user_adapter import TIMEOUT_EVENT_TYPE, question_resolution

        try:
            with self._state_lock:
                with self._task_state_guard(task_id):
                    state = self._read_task_sync(task_id)
                    if state.get("status") in TERMINAL_STATUSES:
                        return
                    status, _event = question_resolution(state.get("messages"), question_id)
                    if status != "pending":
                        return
                    self._append_event_unlocked(
                        state,
                        {
                            "type": TIMEOUT_EVENT_TYPE,
                            "question_id": question_id,
                            "content": "管理员未在时限内回答",
                        },
                    )
                    atomic_write_json(self._task_path(task_id), state)
        except UserModuleAgentTaskNotFoundError:
            return
        logger.info("模块生成任务提问超时: task_id=%s question_id=%s", task_id, question_id)

    async def submit_answer(
        self,
        task_id: str,
        *,
        requester_id: str,
        question_id: str,
        selected: Optional[str] = None,
        free_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await asyncio.wait_for(
            asyncio.to_thread(
                self._submit_answer_sync,
                task_id,
                requester_id=requester_id,
                question_id=question_id,
                selected=selected,
                free_text=free_text,
            ),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    def _submit_answer_sync(
        self,
        task_id: str,
        *,
        requester_id: str,
        question_id: str,
        selected: Optional[str] = None,
        free_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        from services.user_module_ask_user_adapter import (
            ANSWER_EVENT_TYPE,
            assemble_user_input,
            question_resolution,
        )

        selected_value = str(selected or "").strip() or None
        free_text_value = str(free_text or "").strip() or None
        if not selected_value and not free_text_value:
            raise UserModuleAgentAnswerError(
                "必须提供 selected 或 free_text",
                code="answer_payload_required",
                status_code=400,
            )

        try:
            state = self._read_task_sync(task_id)
        except UserModuleAgentTaskNotFoundError:
            raise UserModuleAgentTaskNotFoundError("模块生成任务不存在") from None
        if str(state.get("created_by")) != str(requester_id):
            raise UserModuleAgentTaskNotFoundError("模块生成任务不存在")

        state = self._reconcile_interrupted_task_sync(task_id)
        if state.get("status") in TERMINAL_STATUSES:
            if state.get("error_code") == "agent_task_interrupted":
                raise UserModuleAgentAnswerError(
                    "任务已中断，请重新发起",
                    code="agent_task_interrupted",
                    status_code=409,
                )
            raise UserModuleAgentAnswerError(
                "任务已结束，无法作答",
                code="agent_task_not_running",
                status_code=409,
            )

        with self._state_lock:
            with self._task_state_guard(task_id):
                state = self._read_task_sync(task_id)
                if str(state.get("created_by")) != str(requester_id):
                    raise UserModuleAgentTaskNotFoundError("模块生成任务不存在")
                if state.get("status") in TERMINAL_STATUSES:
                    raise UserModuleAgentAnswerError(
                        "任务已结束，无法作答",
                        code="agent_task_not_running",
                        status_code=409,
                    )
                status, _event = question_resolution(state.get("messages"), question_id)
                if status == "missing":
                    raise UserModuleAgentAnswerError(
                        "提问不存在",
                        code="question_not_found",
                        status_code=404,
                    )
                if status == "answered":
                    raise UserModuleAgentAnswerError(
                        "该问题已回答",
                        code="question_already_answered",
                        status_code=409,
                    )
                if status == "timeout":
                    raise UserModuleAgentAnswerError(
                        "该问题已超时",
                        code="question_timed_out",
                        status_code=409,
                    )
                options = self._question_options(state.get("messages"), question_id)
                allowed = {str(option.get("value") or "") for option in options}
                if selected_value and allowed and selected_value not in allowed:
                    raise UserModuleAgentAnswerError(
                        "selected 不在可选列表中",
                        code="invalid_selected_option",
                        status_code=400,
                    )
                now = _utc_now()
                user_input = assemble_user_input(
                    options=options,
                    selected=selected_value,
                    free_text=free_text_value,
                )
                event = {
                    "type": ANSWER_EVENT_TYPE,
                    "question_id": question_id,
                    "selected": selected_value,
                    "free_text": free_text_value,
                    "answered_by": str(requester_id),
                    "answered_at": now,
                    "content": user_input,
                    "created_at": now,
                }
                self._append_event_unlocked(state, event)
                atomic_write_json(self._task_path(task_id), state)
        logger.info(
            "模块生成任务收到回答: task_id=%s question_id=%s answered_by=%s",
            task_id,
            question_id,
            requester_id,
        )
        return {
            "question_id": question_id,
            "answered_at": now,
            "selected": selected_value,
            "free_text": free_text_value,
        }

    async def cancel_task(self, task_id: str, *, requester_id: str) -> Dict[str, Any]:
        """管理员停止生成：立即把任务置为 cancelled 终态（幂等，终态任务原样返回）。

        协作式取消：执行线程无法被硬杀，会在下一个迭代检查点
        （ExpertAgent._run_task_loop 开头 / 提问等待轮询）感知终态后退出；
        若此刻恰有 LLM 调用正在进行，则在该调用结束后停止。
        """
        return await asyncio.wait_for(
            asyncio.to_thread(self._cancel_task_sync, task_id, requester_id=str(requester_id)),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    def _cancel_task_sync(self, task_id: str, *, requester_id: str) -> Dict[str, Any]:
        state = self._read_task_sync(task_id)
        if str(state.get("created_by")) != str(requester_id):
            raise UserModuleAgentTaskNotFoundError("模块生成任务不存在")
        if state.get("status") in TERMINAL_STATUSES:
            return state
        logger.info("模块生成任务被管理员停止: task_id=%s by=%s", task_id, requester_id)
        return self._update_task_sync(
            task_id,
            {
                "status": "cancelled",
                "error_code": "agent_task_cancelled",
                "error": "管理员已停止生成",
                "completed_at": _utc_now(),
            },
        )

    def is_task_cancelled(self, task_id: str) -> bool:
        """供执行线程迭代检查点调用：任务是否已被管理员停止。"""
        try:
            state = self._read_task_sync(task_id)
        except UserModuleAgentTaskNotFoundError:
            return True
        return state.get("status") == "cancelled"

    def _reconcile_interrupted_task_sync(self, task_id: str) -> Dict[str, Any]:
        """读取时收敛失去执行 worker 的任务；活跃 worker 通过心跳避免误判。"""

        with self._state_lock:
            with self._task_state_guard(task_id):
                state = self._read_task_sync(task_id)
                if state.get("status") not in {"queued", "running"}:
                    return state
                heartbeat_value = (
                    state.get("heartbeat_at") or state.get("updated_at") or state.get("created_at")
                )
                try:
                    heartbeat_at = datetime.fromisoformat(str(heartbeat_value))
                    if heartbeat_at.tzinfo is None:
                        heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
                    elapsed = time.time() - heartbeat_at.timestamp()
                except (TypeError, ValueError, OverflowError):
                    elapsed = self.stale_timeout_seconds + 1
                if elapsed <= self.stale_timeout_seconds:
                    return state
                now = _utc_now()
                state.update(
                    {
                        "status": "failed",
                        "error_code": "agent_task_interrupted",
                        "error": "执行该任务的工作进程已中断；凭据不会落盘，因此任务不能自动恢复，请重新创建任务",
                        "interrupted_at": now,
                        "completed_at": now,
                        "updated_at": now,
                    }
                )
                atomic_write_json(self._task_path(task_id), state)
                return state

    async def create_task(
        self,
        *,
        module_id: str,
        requirement: str,
        created_by: str,
        auth_token: str,
        model: str,
        model_id: int,
        vendor_id: int,
        enable_thinking: bool = False,
        thinking_effort: str = "medium",
        language: str = "zh-CN",
        connector: str = USER_MODULE_HTTP_CONNECTOR,
        comfyui_base_url: Optional[str] = None,
        workflow_json: Optional[str] = None,
        workflow_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_connector = str(connector or USER_MODULE_HTTP_CONNECTOR).strip() or USER_MODULE_HTTP_CONNECTOR
        max_questions = self.max_questions
        if normalized_connector == USER_MODULE_COMFYUI_CONNECTOR:
            max_questions = max(self.max_questions, int(USER_MODULE_AGENT_TASK_MAX_QUESTIONS_COMFYUI))
            requirement = str(requirement or "").strip() or DEFAULT_COMFYUI_REQUIREMENT
        execution_lock = self._acquire_execution_slot()
        try:
            generation = await self.generation_service.create(
                module_id=module_id,
                requirement=requirement,
                created_by=created_by,
                review_model=model,
                review_model_id=model_id,
                review_vendor_id=vendor_id,
            )
            generation_id = generation["generation_id"]
            if normalized_connector == USER_MODULE_COMFYUI_CONNECTOR:
                try:
                    base_url = normalize_base_url(comfyui_base_url or "")
                    workflow_text = await asyncio.wait_for(
                        asyncio.to_thread(
                            load_comfyui_workflow_text,
                            workflow_json=workflow_json,
                            workflow_path=workflow_path,
                        ),
                        timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
                    )
                except (ComfyUIError, ValueError) as exc:
                    raise UserModuleAgentCreateError(str(exc), code="invalid_comfyui_input") from exc
                comfy_meta = json.dumps(
                    {
                        "base_url": base_url,
                        "network_host": host_port_from_base_url(base_url),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                await self.generation_service.write_file(
                    generation_id, "vendor/workflow.json", workflow_text
                )
                await self.generation_service.write_file(
                    generation_id, "vendor/comfyui.json", comfy_meta
                )
            task_id = str(uuid.uuid4())
            now = _utc_now()
            state = {
                "task_id": task_id,
                "generation_id": generation_id,
                "module_id": module_id,
                "requirement": requirement,
                "connector": normalized_connector,
                "max_questions": max_questions,
                "created_by": str(created_by),
                "agent_name": USER_MODULE_AGENT_NAME,
                "worker_instance_id": self.worker_instance_id,
                "recovery_policy": RECOVERY_POLICY,
                "model": model,
                "model_id": int(model_id),
                "vendor_id": int(vendor_id),
                "enable_thinking": bool(enable_thinking),
                "thinking_effort": thinking_effort,
                "language": language,
                "status": "queued",
                "messages": [
                    {
                        "id": 1,
                        "type": "queued",
                        "content": STATUS_EVENT_CONTENT["queued"],
                        "created_at": now,
                    }
                ],
                "next_message_id": 2,
                "result": None,
                "error": None,
                "error_code": None,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "completed_at": None,
                "heartbeat_at": now,
                "interrupted_at": None,
            }
            # auth_token 只能通过线程参数传递，不能加入 state。
            await asyncio.wait_for(
                asyncio.to_thread(atomic_write_json, self._task_path(task_id), state),
                timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
            )
            thread = threading.Thread(
                target=self._run_task,
                name=f"user-module-agent-{task_id[:8]}",
                kwargs={
                    "task_id": task_id,
                    "auth_token": auth_token,
                    "execution_lock": execution_lock,
                },
                daemon=True,
            )
            with self._threads_lock:
                self._threads[task_id] = thread
            try:
                thread.start()
            except Exception:
                with self._threads_lock:
                    self._threads.pop(task_id, None)
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self._update_task_sync,
                        task_id,
                        {
                            "status": "failed",
                            "error_code": "agent_task_start_failed",
                            "error": "模块生成智能体任务启动失败",
                            "completed_at": _utc_now(),
                        },
                    ),
                    timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
                )
                raise
            return state
        except Exception:
            self._release_execution_slot(execution_lock)
            raise

    def _list_tasks_sync(self, *, limit: int, requester_id: str) -> List[Dict[str, Any]]:
        """按 mtime 倒序只读取最近 N 个任务文件的摘要，供管理页重新打开进度弹窗。"""
        try:
            candidates = sorted(
                self.task_root.glob("*.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return []
        summaries: List[Dict[str, Any]] = []
        for path in candidates:
            if len(summaries) >= max(1, int(limit)):
                break
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            if requester_id and str(payload.get("created_by") or "") != str(requester_id):
                continue
            summaries.append(
                {
                    "task_id": payload.get("task_id") or path.stem,
                    "module_id": payload.get("module_id"),
                    "status": payload.get("status"),
                    "generation_id": payload.get("generation_id"),
                    "created_at": payload.get("created_at"),
                    "updated_at": payload.get("updated_at"),
                }
            )
        return summaries

    async def list_tasks(
        self, *, limit: int = 10, requester_id: str = ""
    ) -> List[Dict[str, Any]]:
        return await asyncio.wait_for(
            asyncio.to_thread(self._list_tasks_sync, limit=limit, requester_id=requester_id),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )

    async def get_task(
        self,
        task_id: str,
        *,
        requester_id: str,
        after_id: int = 0,
    ) -> Dict[str, Any]:
        state = await asyncio.wait_for(
            asyncio.to_thread(self._read_task_sync, task_id),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )
        if str(state.get("created_by")) != str(requester_id):
            # 不向其他管理员泄露任务是否存在。
            raise UserModuleAgentTaskNotFoundError("模块生成任务不存在")
        state = await asyncio.wait_for(
            asyncio.to_thread(self._reconcile_interrupted_task_sync, task_id),
            timeout=USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
        )
        generation = await self.generation_service.get(state["generation_id"])
        files = await self.generation_service.list_files(state["generation_id"])
        return {
            **state,
            "messages": [
                message
                for message in list(state.get("messages") or [])
                if int(message.get("id") or 0) > int(after_id)
            ],
            "generation": generation,
            "files": files,
        }

    def _run_task(
        self,
        *,
        task_id: str,
        auth_token: str,
        execution_lock: FileLock,
    ) -> None:
        heartbeat_stop = threading.Event()
        timed_out = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"user-module-agent-heartbeat-{task_id[:8]}",
            args=(task_id, heartbeat_stop),
            daemon=True,
        )
        heartbeat_thread.start()

        def _on_wall_clock_timeout() -> None:
            """挂钟超时兜底：标记失败并停止心跳。

            Python 线程无法被硬杀，_execute_expert 可能仍在阻塞；但 _update_task_sync
            的终态保护会让后续任何 completed/failed 更新失效，任务会停在 failed 终态。
            （见 docs/backend/user_modules_review.md M4）
            """
            if timed_out.is_set():
                return
            timed_out.set()
            heartbeat_stop.set()  # 停止心跳，避免继续刷新 heartbeat_at
            logger.warning("用户模块生成智能体任务挂钟超时 task_id=%s", task_id)
            try:
                self._update_task_sync(
                    task_id,
                    {
                        "status": "failed",
                        "error_code": "agent_task_wall_clock_timeout",
                        "error": "任务超过最长执行时间，已被强制终止",
                        "completed_at": _utc_now(),
                    },
                )
            except Exception:
                logger.exception("标记挂钟超时失败 task_id=%s", task_id)

        wall_clock_guard = WallClockGuard(
            self.wall_clock_timeout_seconds,
            _on_wall_clock_timeout,
        )
        with self._threads_lock:
            self._wall_clock_guards[task_id] = wall_clock_guard
        wall_clock_guard.start()

        try:
            state = self._update_task_sync(
                task_id,
                {"status": "running", "started_at": _utc_now()},
            )
            # 排队期间被管理员取消：状态已是 cancelled 终态，无需再启动智能体
            if state.get("status") == "cancelled":
                return
            result = self._execute_expert(state=state, auth_token=auth_token)
            # 挂钟超时已由 Timer 标记 failed（终态），跳过后续步骤
            if timed_out.is_set():
                return
            result_text = str(result.get("result") or "")[:USER_MODULE_AGENT_TASK_RESULT_MAX_CHARS]
            final_generation = asyncio.run(
                self.generation_service.get(state["generation_id"])
            )
            if not result.get("success"):
                raise RuntimeError(str(result.get("error") or "模块生成智能体执行失败"))
            if (
                final_generation.get("status") != "validated"
                or not (final_generation.get("validation") or {}).get("ok")
            ):
                raise RuntimeError("智能体未完成模块校验；请重新生成或在草稿页检查校验报告")
            review_gate = final_generation.get("review_gate") or {}
            if review_gate.get("required") and review_gate.get("publishable") is not True:
                raise RuntimeError(
                    str(
                        review_gate.get("reason")
                        or "AI 安全审核未完成；请在草稿页重新校验并检查审核模型"
                    )
                )
            self._update_task_sync(
                task_id,
                {
                    "status": "completed",
                    "result": result_text,
                    "error_code": None,
                    "generation_status": final_generation.get("status"),
                    "completed_at": _utc_now(),
                },
            )
        except Exception as exc:
            # 挂钟超时已由 Timer 标记终态，避免覆盖 error_code
            if not timed_out.is_set():
                logger.exception("用户模块生成智能体任务失败 task_id=%s", task_id)
                self._update_task_sync(
                    task_id,
                    {
                        "status": "failed",
                        "error_code": "agent_task_failed",
                        "error": str(exc)[:4000],
                        "completed_at": _utc_now(),
                    },
                )
        finally:
            wall_clock_guard.cancel()
            with self._threads_lock:
                self._wall_clock_guards.pop(task_id, None)
                self._threads.pop(task_id, None)
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=self.heartbeat_interval_seconds + 0.5)
            self._release_execution_slot(execution_lock)

    def _execute_expert(self, *, state: Dict[str, Any], auth_token: str) -> Dict[str, Any]:
        from script_writer_core.agents.expert_agent import ExpertAgent
        from script_writer_core.agents.tool_executor import ToolExecutor
        from script_writer_core.file_manager import FileManager
        from services.user_module_ask_user_adapter import BackgroundAskUserAdapter

        config = json.loads(self.agents_config_path.read_text(encoding="utf-8"))
        expert_config = config.get("expert_agents", {}).get(USER_MODULE_AGENT_NAME)
        if not isinstance(expert_config, dict):
            raise RuntimeError("用户模块生成专家未注册")

        # ExpertAgent 的遗留 HistoryManager 初始化时会建目录。为避免污染剧本 world/session，
        # 给它一个任务期临时根目录；真正任务状态只写 module_root/state/agent-tasks。
        with tempfile.TemporaryDirectory(prefix="zjt-module-agent-") as temporary_root:
            file_manager = FileManager(base_dir=temporary_root)
            allowed_tools = [
                tool
                for tool in list(expert_config.get("allowed_tools") or [])
                if tool != "user_module_generation_create"
            ]
            ask_user_adapter = BackgroundAskUserAdapter(self, state["task_id"])
            expert = ExpertAgent(
                skill_names=list(expert_config.get("skills") or [USER_MODULE_AGENT_NAME]),
                model=state["model"],
                allowed_tools=allowed_tools,
                context_from_pm=(
                    "这是后台管理员发起的专用用户模块开发任务。"
                    f"generation_id={state['generation_id']} 已由系统创建；"
                    "必须直接在该 generation 中工作，禁止再次调用 "
                    "user_module_generation_create。完成代码后必须校验，但不得审批或激活。"
                ),
                file_manager=file_manager,
                user_id=state["created_by"],
                world_id="user-modules",
                auth_token=auth_token,
                tool_executor=ToolExecutor(file_manager),
                vendor_id=state["vendor_id"],
                model_id=state["model_id"],
                enable_thinking=state["enable_thinking"],
                thinking_effort=state["thinking_effort"],
                max_iterations=int(expert_config.get("max_iterations", 30)),
                language=state["language"],
                max_consecutive_no_progress=int(expert_config.get("max_consecutive_no_progress", 3)),
                max_consecutive_errors=int(expert_config.get("max_consecutive_errors", 3)),
                max_total_errors=int(expert_config.get("max_total_errors", 7)),
                task_manager=ask_user_adapter,
                task_id=state["task_id"],
            )

            class _NoopHistoryManager:
                @staticmethod
                def save_expert_session(**_kwargs):
                    return None

            expert.history_manager = _NoopHistoryManager()
            description = (
                f"为模块 {state['module_id']} 实现以下需求：\n{state['requirement']}\n\n"
                f"系统已创建 generation_id={state['generation_id']}。"
                "不要创建新的 generation；先查询公开协议，再使用 generation read/write 工具在该草稿中"
                "生成 manifest.json、src/driver.py、README.md 和测试，最后运行校验并总结风险。"
            )
            if state.get("connector") == USER_MODULE_COMFYUI_CONNECTOR:
                description += (
                    "\n\n本任务 connector=local_comfyui。"
                    "staging 已包含 vendor/workflow.json 与 vendor/comfyui.json。"
                    "必须先读取这两份文件；把 comfyui.json 的 base_url 写入 src/settings.py 的 "
                    "COMFYU_BASE_URL；工作流转成 src/workflow_graph.py；用 "
                    "module_runtime.comfyui 的 infer_mapping/apply_mapping/LocalComfyUIClient。"
                    "manifest.secret_names 必须为空；network_hosts 只声明该 ComfyUI 的 host:port。"
                    "禁止 ask_user 再问 ComfyUI 地址或 webhook。"
                    f"本任务最多可 ask_user {int(state.get('max_questions') or USER_MODULE_AGENT_TASK_MAX_QUESTIONS_COMFYUI)} 次以确认节点映射。"
                    "resource_limits.operation_timeout_seconds 设为 900。"
                )
            else:
                description += self._grantable_secret_prompt()
            return expert.execute_task(
                {
                    "session_id": task_id_from_state(state),
                    "description": description,
                    "conversation_history": [],
                }
            )

    @staticmethod
    def _grantable_secret_prompt() -> str:
        """HTTP 供应商任务注入平台可授权密钥清单，避免 LLM 自造密钥名或猜错槽位。"""
        from module_runtime.secret_resolver import user_module_grantable_catalog

        catalog = user_module_grantable_catalog()
        if not catalog:
            return ""
        catalog_lines = "\n".join(
            f"- {name}（后台配置 {'.'.join(path)}{'；' + desc if desc else ''}）"
            for name, (path, desc) in sorted(catalog.items())
        )
        return (
            "\n\n平台可授权密钥清单：manifest 的 secret_names 只能从下列名称中选取"
            "（静态校验会拒绝清单外的名称）：\n" + catalog_lines + "\n"
            "密钥值由平台运行时注入 ctx.secrets，代码用 ctx.secrets.get(\"名称\") 读取，"
            "禁止在代码/文档中写死密钥值。密钥槽位选择规则：\n"
            "1. 清单中存在与当前供应商一一对应的名称（如需求是 RunningHub 而清单有 "
            "RUNNINGHUB_API_KEY）时直接选用，无需提问；此时不得改选 api_aggregator.site_N "
            "等编号/共用槽位，也不得再就密钥来源 ask_user。\n"
            "2. 当前供应商是聚合站/中转站，或其凭据只能对应 api_aggregator.site_N 这类"
            "编号/共用槽位时，槽位与供应商的实际对应关系只有管理员知道：**必须用 "
            "ask_user 请管理员确认该供应商的密钥配在哪个槽位**，选项逐个列出候选槽位的"
            "后台配置名与描述（外加「都不在，需要平台新增配置」）；禁止按编号顺序、"
            "描述相似度或任何方式猜测选定。\n"
            "3. 清单中完全没有可承载当前供应商凭据的名称时，secret_names 留空并在"
            "总结中说明需要平台扩展可授权配置。"
        )


def task_id_from_state(state: Dict[str, Any]) -> str:
    return str(state["task_id"])


_default_service: Optional[UserModuleAgentService] = None
_default_service_lock = threading.Lock()


def get_user_module_agent_service() -> UserModuleAgentService:
    global _default_service
    with _default_service_lock:
        if _default_service is None:
            _default_service = UserModuleAgentService()
        return _default_service
