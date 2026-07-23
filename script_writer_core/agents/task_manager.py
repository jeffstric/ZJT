from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Any, List
import threading
import queue
import uuid
import logging
import os
import time
from config.constant import FilePathConstants
from model.agent_tasks import AgentTasksModel, AgentTaskEntity
from model.agent_task_messages import AgentTaskMessagesModel
from model.agent_verifications import AgentVerificationsModel, AgentVerificationEntity

logger = logging.getLogger(__name__)


def process_long_input(user_id: str, world_id: str, user_message: str) -> Dict[str, Any]:
    """
    处理长文本输入，如果超过5000字则截取并保存完整内容到文件
    
    Args:
        user_id: 用户ID
        world_id: 世界ID
        user_message: 用户输入的消息
    
    Returns:
        dict: 包含处理后的消息、文件引用和原始长度
        {
            "processed_message": "处理后的消息（前4000+后1000）",
            "file_reference": "文件名（如果有）",
            "original_length": 原始长度
        }
    """
    # 判断长度
    if len(user_message) <= 5000:
        return {
            "processed_message": user_message,
            "file_reference": None,
            "original_length": len(user_message)
        }
    
    # 截取内容：前4000字 + 后1000字
    prefix = user_message[:4000]
    suffix = user_message[-1000:]
    
    # 生成文件名：HH:mm:ss.txt
    timestamp = datetime.now().strftime("%H:%M:%S")
    filename = f"{timestamp}.txt"
    
    # 保存完整内容到文件
    file_dir = os.path.join(FilePathConstants._SCRIPT_WRITER_USER_DATA_SUBDIR, str(user_id), str(world_id), "user_long_input")
    os.makedirs(file_dir, exist_ok=True)
    
    file_path = os.path.join(file_dir, filename)
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(user_message)
        
        # 构造处理后的消息
        middle_omitted = len(user_message) - 5000
        processed_message = f"""【系统提示】用户输入的内容超过5000字，已自动保存完整内容。
- 文件名：{filename}
- 原始长度：{len(user_message)} 字
- 如需读取完整内容，请调用工具：get_long_user_input(name="{filename}")
- 可选参数 limit 用于限制返回字符数，例如：get_long_user_input(name="{filename}", limit=10000)

⚠️ 重要提醒：如果需要调用子智能体处理此内容，请务必在调用时将文件名 "{filename}" 传递给子智能体，否则子智能体会由于没有正确传入文件名，而无法访问完整内容。

【用户输入内容（已截取）】
{prefix}

... [中间内容已省略，共 {middle_omitted} 字] ...

{suffix}
"""
        
        return {
            "processed_message": processed_message,
            "file_reference": filename,
            "original_length": len(user_message)
        }
        
    except Exception as e:
        # 如果保存失败，返回原始消息
        logger.error(f"保存长文本输入失败: {e}")
        return {
            "processed_message": user_message,
            "file_reference": None,
            "original_length": len(user_message),
            "error": f"保存文件失败: {str(e)}"
        }


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VerificationStatus(Enum):
    """验证状态枚举"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass
class VerificationRequest:
    """人工验证请求（轻量内存对象，持久化到数据库）"""
    verification_id: str
    task_id: str
    verification_type: str
    title: str
    description: str
    options: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    status: VerificationStatus = VerificationStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "verification_id": self.verification_id,
            "task_id": self.task_id,
            "verification_type": self.verification_type,
            "title": self.title,
            "description": self.description,
            "options": self.options,
            "context": self.context,
            "status": self.status.value,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class AgentTask:
    """智能体任务"""
    task_id: str
    session_id: str
    user_message: str
    user_id: str
    world_id: str
    auth_token: str
    vendor_id: int
    model_id: int
    enable_thinking: bool = False
    thinking_effort: str = "medium"
    image_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None
    audio_urls: Optional[List[str]] = None
    thumbnail_urls: Optional[List[str]] = None
    execution_context_json: Optional[Dict[str, Any]] = None
    language: str = "zh-CN"
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: float = 0.0
    current_step: str = ""
    message_queue: queue.Queue = field(default_factory=queue.Queue)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "user_message": self.user_message,
            "user_id": self.user_id,
            "world_id": self.world_id,
            "auth_token": self.auth_token,
            "vendor_id":self.vendor_id,
            "model_id":self.model_id,
            "enable_thinking": self.enable_thinking,
            "thinking_effort": self.thinking_effort,
            "image_urls": self.image_urls,
            "video_urls": self.video_urls,
            "audio_urls": self.audio_urls,
            "execution_context_json": self.execution_context_json,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "progress": self.progress,
            "current_step": self.current_step
        }


class TaskManager:
    """任务管理器 - 管理后台任务的生命周期"""
    
    def __init__(self):
        self.tasks: Dict[str, AgentTask] = {}
        self.task_threads: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        logger.info("TaskManager initialized")
    
    def create_task(
        self,
        session_id: str,
        user_message: str,
        user_id: str,
        world_id: str,
        auth_token: str,
        vendor_id: int,
        model_id: int,
        enable_thinking: bool = False,
        thinking_effort: str = "medium",
        image_urls: Optional[List[str]] = None,
        video_urls: Optional[List[str]] = None,
        audio_urls: Optional[List[str]] = None,
        thumbnail_urls: Optional[List[str]] = None,
        language: str = "zh-CN",
        execution_context_json: Optional[Dict[str, Any]] = None,
    ) -> str:
        """创建新任务，返回 task_id"""
        # 处理长文本输入
        processed_result = process_long_input(
            user_id=user_id,
            world_id=world_id,
            user_message=user_message
        )

        # 使用处理后的消息
        actual_message = processed_result["processed_message"]

        # 记录长文本处理信息
        if processed_result.get("file_reference"):
            logger.info(
                f"长文本已处理：原始 {processed_result['original_length']} 字，"
                f"文件：{processed_result['file_reference']}"
            )

        task_id = str(uuid.uuid4())
        logger.info(f"Creating AgentTask with language='{language}'")
        task = AgentTask(
            task_id=task_id,
            session_id=session_id,
            user_message=actual_message,
            user_id=user_id,
            world_id=world_id,
            auth_token=auth_token,
            vendor_id=vendor_id,
            model_id=model_id,
            enable_thinking=enable_thinking,
            thinking_effort=thinking_effort,
            image_urls=image_urls,
            video_urls=video_urls,
            audio_urls=audio_urls,
            thumbnail_urls=thumbnail_urls,
            execution_context_json=execution_context_json,
            language=language,
        )
        logger.info(f"AgentTask created, task.language='{task.language}'")

        # 写入数据库（唯一数据源，跨进程共享）
        try:
            AgentTasksModel.create(
                task_id=task_id,
                session_id=session_id,
                user_id=user_id,
                world_id=world_id,
                user_message=actual_message,
                auth_token=auth_token,
                vendor_id=vendor_id,
                model_id=model_id,
                enable_thinking=enable_thinking,
                thinking_effort=thinking_effort,
                image_urls=image_urls,
                video_urls=video_urls,
                audio_urls=audio_urls,
                status='pending',
                language=language,
                execution_context_json=execution_context_json,
            )
        except Exception as e:
            logger.error(f"Failed to save task to database: {e}")
            raise

        # 保存到内存（仅用于后台线程执行，不作为查询缓存）
        # 注意：内存中的 task 对象包含 message_queue，用于线程间通信
        with self._lock:
            self.tasks[task_id] = task

        logger.info(f"Created task {task_id} for session {session_id}")
        return task_id
    
    def get_task(self, task_id: str) -> Optional[AgentTask]:
        """
        获取任务（统一从数据库获取，确保数据一致性）

        注意：不使用内存缓存，避免多 worker 环境下的数据不一致问题。
        内存中的 task 对象仅用于后台线程执行，不用于状态查询。
        """
        # 统一从数据库获取（确保跨 worker 数据一致）
        try:
            db_task = AgentTasksModel.get_by_task_id(task_id)
            if db_task:
                # 转换为 AgentTask 对象
                task = AgentTask(
                    task_id=db_task.task_id,
                    session_id=db_task.session_id,
                    user_message=db_task.user_message,
                    user_id=db_task.user_id,
                    world_id=db_task.world_id,
                    auth_token=db_task.auth_token,
                    vendor_id=db_task.vendor_id,
                    model_id=db_task.model_id,
                    enable_thinking=str(getattr(db_task, 'enable_thinking', False)).lower() == 'true',
                    thinking_effort=getattr(db_task, 'thinking_effort', 'medium'),
                    image_urls=getattr(db_task, 'image_urls', None),
                    video_urls=getattr(db_task, 'video_urls', None),
                    audio_urls=getattr(db_task, 'audio_urls', None),
                    execution_context_json=getattr(db_task, 'execution_context_json', None),
                    language=getattr(db_task, 'language', 'zh-CN'),
                    status=TaskStatus(db_task.status),
                    progress=db_task.progress,
                    current_step=db_task.current_step,
                    error=db_task.error,
                    result=db_task.result
                )
                task.created_at = db_task.created_at
                task.started_at = db_task.started_at
                task.completed_at = db_task.completed_at
                return task
        except Exception as e:
            logger.error(f"Failed to get task from database: {e}")

        return None

    def merge_task_media(
        self,
        task_id: str,
        image_urls: Optional[List[str]] = None,
        video_urls: Optional[List[str]] = None,
        audio_urls: Optional[List[str]] = None,
        thumbnail_urls: Optional[List[str]] = None,
    ) -> None:
        """Merge media URLs into the in-memory task used by the running worker."""
        def _merge(existing, incoming):
            merged = list(existing or [])
            for url in incoming or []:
                if isinstance(url, str) and url and url not in merged:
                    merged.append(url)
            return merged or None

        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task.image_urls = _merge(task.image_urls, image_urls)
            task.video_urls = _merge(task.video_urls, video_urls)
            task.audio_urls = _merge(task.audio_urls, audio_urls)
            task.thumbnail_urls = _merge(task.thumbnail_urls, thumbnail_urls)

    def task_exists(self, task_id: str) -> bool:
        """检查任务是否存在（数据库）"""
        try:
            db_task = AgentTasksModel.get_by_task_id(task_id)
            return db_task is not None
        except Exception as e:
            logger.error(f"Failed to check task existence: {e}")
            return False
    
    def push_message(self, task_id: str, message_type: str, content: Dict[str, Any]):
        """推送消息到数据库（跨进程共享，SSE 统一从数据库轮询）"""
        try:
            record_id = AgentTaskMessagesModel.create(
                task_id=task_id,
                message_type=message_type,
                content=content
            )
            logger.warning(f"[DUPLICATE-DEBUG] Message pushed to DB: task_id={task_id}, type={message_type}, record_id={record_id}")
        except Exception as e:
            logger.error(f"Failed to push message to database: {e}")

    def start_task(self, task: AgentTask, pm_agent, session_data: Dict[str, Any], on_complete=None):
        """在后台线程中启动任务"""
        logger.warning(f"[DEBUG] start_task 被调用: task_id={task.task_id}, pm_agent={pm_agent.agent_id if pm_agent else 'None'}")

        def run_task():
            try:
                logger.warning(f"[DEBUG] run_task 线程开始执行: {task.task_id}")
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.now()
                logger.info(f"Starting task {task.task_id}")

                # 更新数据库状态
                try:
                    AgentTasksModel.update_status(
                        task_id=task.task_id,
                        status='running',
                        started_at=task.started_at
                    )
                except Exception as e:
                    logger.error(f"Failed to update task status in database: {e}")

                # 推送消息到数据库和内存队列
                self.push_message(task.task_id, 'status', {
                    'status': 'running',
                    'message': '任务开始执行'
                })

                logger.warning(f"[DEBUG] 准备调用 pm_agent.execute()")
                from script_writer_core.mcp_tool import scoped_media_generation_snapshots
                execution_context = task.execution_context_json or {}
                with scoped_media_generation_snapshots(
                    execution_context.get('generation_snapshots') or {}
                ):
                    result = pm_agent.execute(task, session_data)
                logger.warning(f"[DEBUG] pm_agent.execute() 执行完成")

                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
                task.result = result

                # 更新数据库状态
                try:
                    AgentTasksModel.update_status(
                        task_id=task.task_id,
                        status='completed',
                        completed_at=task.completed_at,
                        result=result
                    )
                except Exception as e:
                    logger.error(f"Failed to update task status in database: {e}")

                # 推送完成消息
                self.push_message(task.task_id, 'done', {
                    'status': 'completed',
                    'result': result
                })

                logger.info(f"Task {task.task_id} completed successfully")

                # 调用完成回调
                if on_complete:
                    try:
                        on_complete(result)
                    except Exception as e:
                        logger.error(f"on_complete callback failed: {e}", exc_info=True)

            except Exception as e:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now()
                task.error = str(e)

                # 更新数据库状态
                try:
                    AgentTasksModel.update_status(
                        task_id=task.task_id,
                        status='failed',
                        completed_at=task.completed_at,
                        error=str(e)
                    )
                except Exception as db_e:
                    logger.error(f"Failed to update task status in database: {db_e}")

                # 推送错误消息
                self.push_message(task.task_id, 'error', {
                    'status': 'failed',
                    'error': str(e)
                })

                logger.error(f"Task {task.task_id} failed: {e}", exc_info=True)

        thread = threading.Thread(target=run_task, daemon=True)
        with self._lock:
            self.task_threads[task.task_id] = thread
        thread.start()
        logger.info(f"Task {task.task_id} thread started")
    
    def create_verification(
        self,
        task_id: str,
        verification_type: str,
        title: str,
        description: str,
        options: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> VerificationRequest:
        """创建人工验证请求（持久化到数据库，支持跨进程）"""
        verification_id = str(uuid.uuid4())
        verification = VerificationRequest(
            verification_id=verification_id,
            task_id=task_id,
            verification_type=verification_type,
            title=title,
            description=description,
            options=options or [],
            context=context or {}
        )

        # 写入数据库（跨进程共享）
        try:
            AgentVerificationsModel.create(
                verification_id=verification_id,
                task_id=task_id,
                verification_type=verification_type,
                title=title,
                description=description,
                options=options or [],
                context=context or {}
            )
        except Exception as e:
            logger.error(f"Failed to save verification to database: {e}")
            raise

        logger.info(f"Created verification {verification_id} for task {task_id}")
        return verification
    
    def get_verification(self, verification_id: str) -> Optional[AgentVerificationEntity]:
        """获取验证请求（从数据库读取，支持跨进程）"""
        try:
            return AgentVerificationsModel.get_by_verification_id(verification_id)
        except Exception as e:
            logger.error(f"Failed to get verification {verification_id}: {e}")
            return None
    
    def wait_for_verification(
        self,
        verification: VerificationRequest,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """阻塞等待人工验证结果（通过数据库轮询，支持多 Worker）
        ⚠️ 阻塞风险：此函数会阻塞当前线程直到用户验证或超时（默认300秒）
        仅在 Agent 独立线程中调用，禁止在 FastAPI 路由中直接调用
        """
        logger.info(f"Waiting for verification {verification.verification_id}")

        # 在发送前快照验证数据（防止数据竞争）
        verification_dict = verification.to_dict()

        task = self.get_task(verification.task_id)
        if task:
            task.status = TaskStatus.WAITING_HUMAN
            task.message_queue.put({
                "type": "human_verification_required",
                "verification": verification_dict
            })

        # 推送到数据库，让 SSE 可见（无论 task 是否存在）
        self.push_message(verification.task_id, 'human_verification_required', {"verification": verification_dict})

        # 更新任务状态为 waiting_human
        try:
            AgentTasksModel.update_status(
                task_id=verification.task_id,
                status='waiting_human'
            )
        except Exception as e:
            logger.error(f"Failed to update task status to waiting_human: {e}")

        # 轮询数据库等待结果（替代 threading.Event，支持跨进程）
        poll_interval = 0.5  # 500ms 轮询间隔
        elapsed = 0.0

        while elapsed < timeout:
            time.sleep(poll_interval)
            elapsed += poll_interval

            try:
                db_verification = AgentVerificationsModel.get_by_verification_id(
                    verification.verification_id
                )
                if db_verification and db_verification.status != 'pending':
                    # 用户已提交回答
                    logger.info(f"Verification {verification.verification_id} received response: {db_verification.status}")

                    # 恢复任务状态
                    if task:
                        task.status = TaskStatus.RUNNING
                    try:
                        AgentTasksModel.update_status(
                            task_id=verification.task_id,
                            status='running'
                        )
                    except Exception as e:
                        logger.error(f"Failed to restore task status to running: {e}")

                    result = db_verification.result or {}
                    result["success"] = db_verification.status == "approved"
                    result["status"] = db_verification.status  # "approved" 或 "rejected" 等
                    return result
            except Exception as e:
                logger.error(f"Error polling verification {verification.verification_id}: {e}")

        # 超时
        logger.warning(f"Verification {verification.verification_id} timed out after {timeout}s")

        # 更新数据库状态为 cancelled
        try:
            AgentVerificationsModel.submit_result(
                verification.verification_id,
                status='cancelled',
                result={"success": False, "status": "timeout", "error": "验证超时"}
            )
        except Exception as e:
            logger.error(f"Failed to cancel verification on timeout: {e}")

        # 恢复任务状态为 running（超时后 agent 会继续执行）
        if task:
            task.status = TaskStatus.RUNNING
        try:
            AgentTasksModel.update_status(
                task_id=verification.task_id,
                status='running'
            )
        except Exception as e:
            logger.error(f"Failed to restore task status to running after timeout: {e}")

        # 推送超时事件到前端，让前端清除 pendingVerificationId
        self.push_message(verification.task_id, 'verification_timeout', {
            'verification_id': verification.verification_id,
            'error': '验证超时'
        })

        return {"success": False, "status": "timeout", "error": "验证超时"}
    
    def submit_verification(
        self,
        verification_id: str,
        result: Dict[str, Any]
    ) -> bool:
        """提交人工验证结果（写入数据库，支持跨进程）"""
        action = result.get("action")
        if action == "confirm":
            status = "approved"
        elif action == "cancel":
            status = "rejected"
        else:
            status = "cancelled"

        try:
            success = AgentVerificationsModel.submit_result(
                verification_id=verification_id,
                status=status,
                result=result
            )
            if success:
                logger.info(f"Verification {verification_id} submitted with action: {action}")
            return success
        except Exception as e:
            logger.error(f"Failed to submit verification {verification_id}: {e}")
            return False
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        task = self.get_task(task_id)
        if not task:
            return False
        
        with self._lock:
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now()
        
        logger.info(f"Task {task_id} cancelled")
        return True
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务（内存和数据库）"""
        now = datetime.now()
        to_remove = []

        # 清理内存中的旧任务
        with self._lock:
            for task_id, task in self.tasks.items():
                age = (now - task.created_at).total_seconds() / 3600
                if age > max_age_hours and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    to_remove.append(task_id)

            for task_id in to_remove:
                del self.tasks[task_id]
                if task_id in self.task_threads:
                    del self.task_threads[task_id]

        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old tasks from memory")

        # 清理数据库中的旧任务和消息
        try:
            deleted_tasks = AgentTasksModel.delete_old_tasks(max_age_hours)
            deleted_messages = AgentTaskMessagesModel.delete_old_messages(max_age_hours)
            deleted_verifications = AgentVerificationsModel.delete_old_verifications(max_age_hours)
            if deleted_tasks > 0 or deleted_messages > 0 or deleted_verifications > 0:
                logger.info(f"Cleaned up {deleted_tasks} tasks, {deleted_messages} messages, {deleted_verifications} verifications from database")
        except Exception as e:
            logger.error(f"Failed to cleanup old tasks from database: {e}")
