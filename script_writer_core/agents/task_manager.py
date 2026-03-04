from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Any, List
import threading
import queue
import uuid
import logging
import os
from config.constant import FilePathConstants

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
    """人工验证请求"""
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
    response_event: threading.Event = field(default_factory=threading.Event)
    
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
        self.verifications: Dict[str, VerificationRequest] = {}
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
        model_id: int
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
        task = AgentTask(
            task_id=task_id,
            session_id=session_id,
            user_message=actual_message,  # 使用处理后的消息
            user_id=user_id,
            world_id=world_id,
            auth_token=auth_token,
            vendor_id=vendor_id,
            model_id=model_id
        )
        
        with self._lock:
            self.tasks[task_id] = task
        
        logger.info(f"Created task {task_id} for session {session_id}")
        return task_id
    
    def get_task(self, task_id: str) -> Optional[AgentTask]:
        """获取任务"""
        with self._lock:
            return self.tasks.get(task_id)
    
    def start_task(self, task: AgentTask, pm_agent, session_data: Dict[str, Any], on_complete=None):
        """在后台线程中启动任务"""
        logger.warning(f"[DEBUG] start_task 被调用: task_id={task.task_id}, pm_agent={pm_agent.agent_id if pm_agent else 'None'}")

        def run_task():
            try:
                logger.warning(f"[DEBUG] run_task 线程开始执行: {task.task_id}")
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.now()
                logger.info(f"Starting task {task.task_id}")
                
                task.message_queue.put({
                    "type": "status",
                    "status": "running",
                    "message": "任务开始执行"
                })
                
                logger.warning(f"[DEBUG] 准备调用 pm_agent.execute()")
                result = pm_agent.execute(task, session_data)
                logger.warning(f"[DEBUG] pm_agent.execute() 执行完成")
                
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
                task.result = result
                
                task.message_queue.put({
                    "type": "done",
                    "status": "completed",
                    "result": result
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
                
                task.message_queue.put({
                    "type": "error",
                    "status": "failed",
                    "error": str(e)
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
        """创建人工验证请求"""
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
        
        with self._lock:
            self.verifications[verification_id] = verification
        
        logger.info(f"Created verification {verification_id} for task {task_id}")
        return verification
    
    def get_verification(self, verification_id: str) -> Optional[VerificationRequest]:
        """获取验证请求"""
        with self._lock:
            return self.verifications.get(verification_id)
    
    def wait_for_verification(
        self, 
        verification: VerificationRequest, 
        timeout: int = 300
    ) -> Dict[str, Any]:
        """阻塞等待人工验证结果"""
        logger.info(f"Waiting for verification {verification.verification_id}")
        
        task = self.get_task(verification.task_id)
        if task:
            task.status = TaskStatus.WAITING_HUMAN
            task.message_queue.put({
                "type": "human_verification_required",
                "verification": verification.to_dict()
            })
        
        success = verification.response_event.wait(timeout=timeout)
        
        if not success:
            logger.warning(f"Verification {verification.verification_id} timed out")
            verification.status = VerificationStatus.CANCELLED
            return {"success": False, "error": "验证超时"}
        
        if task:
            task.status = TaskStatus.RUNNING
        
        logger.info(f"Verification {verification.verification_id} received response: {verification.status.value}")
        return verification.result or {"success": False, "error": "未知错误"}
    
    def submit_verification(
        self, 
        verification_id: str, 
        result: Dict[str, Any]
    ) -> bool:
        """提交人工验证结果"""
        verification = self.get_verification(verification_id)
        if not verification:
            logger.warning(f"Verification {verification_id} not found")
            return False
        
        with self._lock:
            action = result.get("action")
            if action == "confirm":
                verification.status = VerificationStatus.APPROVED
            elif action == "cancel":
                verification.status = VerificationStatus.REJECTED
            else:
                verification.status = VerificationStatus.CANCELLED
            
            verification.result = result
            verification.response_event.set()
        
        logger.info(f"Verification {verification_id} submitted with action: {action}")
        return True
    
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
        """清理旧任务"""
        now = datetime.now()
        to_remove = []
        
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
            logger.info(f"Cleaned up {len(to_remove)} old tasks")
