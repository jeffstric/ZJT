"""
Agent Tasks Model - Database operations for agent_tasks table
用于跨进程共享任务状态，支持 gunicorn 多 worker 模式
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class AgentTaskEntity:
    """Agent task database entity class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.task_id = kwargs.get('task_id')
        self.session_id = kwargs.get('session_id')
        self.user_id = kwargs.get('user_id')
        self.world_id = kwargs.get('world_id')
        self.user_message = kwargs.get('user_message', '')
        self.auth_token = kwargs.get('auth_token', '')
        self.vendor_id = kwargs.get('vendor_id')
        self.model_id = kwargs.get('model_id')
        self.enable_thinking = kwargs.get('enable_thinking', False)
        self.thinking_effort = kwargs.get('thinking_effort', 'medium')
        self.status = kwargs.get('status', 'pending')
        self.progress = kwargs.get('progress', 0.0)
        self.current_step = kwargs.get('current_step', '')

        # Deserialize result from JSON
        result_json = kwargs.get('result')
        if isinstance(result_json, str) and result_json:
            try:
                self.result = json.loads(result_json)
            except json.JSONDecodeError:
                self.result = None
        else:
            self.result = result_json

        self.error = kwargs.get('error')
        self.created_at = kwargs.get('created_at')
        self.started_at = kwargs.get('started_at')
        self.completed_at = kwargs.get('completed_at')

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'task_id': self.task_id,
            'session_id': self.session_id,
            'user_id': self.user_id,
            'world_id': self.world_id,
            'user_message': self.user_message,
            'auth_token': self.auth_token,
            'vendor_id': self.vendor_id,
            'model_id': self.model_id,
            'enable_thinking': self.enable_thinking,
            'thinking_effort': self.thinking_effort,
            'status': self.status,
            'progress': self.progress,
            'current_step': self.current_step,
            'result': self.result,
            'error': self.error,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }


class AgentTasksModel:
    """Agent tasks database operations"""

    @staticmethod
    def create(
        task_id: str,
        session_id: str,
        user_id: str,
        world_id: str,
        user_message: str,
        auth_token: str = '',
        vendor_id: Optional[int] = None,
        model_id: Optional[int] = None,
        enable_thinking: bool = False,
        thinking_effort: str = 'medium',
        status: str = 'pending'
    ) -> int:
        """
        Create a new agent task

        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO agent_tasks
            (task_id, session_id, user_id, world_id, user_message,
             auth_token, vendor_id, model_id, enable_thinking, thinking_effort, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        # enable_thinking: bool/str -> str（数据库存字符串，支持 true/false/auto）
        enable_thinking_str = str(enable_thinking).lower() if isinstance(enable_thinking, bool) else str(enable_thinking)
        params = (task_id, session_id, user_id, world_id, user_message,
                  auth_token, vendor_id, model_id, enable_thinking_str, thinking_effort, status)

        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created agent task with ID: {record_id}, task_id: {task_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create agent task: {e}")
            raise

    @staticmethod
    def get_by_task_id(task_id: str) -> Optional[AgentTaskEntity]:
        """
        Get task by task_id

        Returns:
            AgentTaskEntity object or None
        """
        sql = "SELECT * FROM agent_tasks WHERE task_id = %s"

        try:
            result = execute_query(sql, (task_id,), fetch_one=True)
            if result:
                return AgentTaskEntity(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get task {task_id}: {e}")
            raise

    @staticmethod
    def update_status(
        task_id: str,
        status: str,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Update task status

        Returns:
            Number of affected rows
        """
        update_fields = ["status = %s"]
        params = [status]

        if started_at:
            update_fields.append("started_at = %s")
            params.append(started_at)

        if completed_at:
            update_fields.append("completed_at = %s")
            params.append(completed_at)

        if error is not None:
            update_fields.append("error = %s")
            params.append(error)

        if result is not None:
            update_fields.append("result = %s")
            params.append(json.dumps(result, ensure_ascii=False))

        params.append(task_id)

        sql = f"""
            UPDATE agent_tasks
            SET {', '.join(update_fields)}
            WHERE task_id = %s
        """

        try:
            affected_rows = execute_update(sql, tuple(params))
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update task status {task_id}: {e}")
            raise

    @staticmethod
    def update_progress(task_id: str, progress: float, current_step: str = '') -> int:
        """
        Update task progress

        Returns:
            Number of affected rows
        """
        sql = """
            UPDATE agent_tasks
            SET progress = %s, current_step = %s
            WHERE task_id = %s
        """

        try:
            affected_rows = execute_update(sql, (progress, current_step, task_id))
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update task progress {task_id}: {e}")
            raise

    @staticmethod
    def list_by_session(session_id: str, limit: int = 100) -> List[AgentTaskEntity]:
        """
        List tasks by session

        Returns:
            List of AgentTaskEntity objects
        """
        sql = """
            SELECT * FROM agent_tasks
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """

        try:
            results = execute_query(sql, (session_id, limit), fetch_all=True)
            return [AgentTaskEntity(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to list tasks for session {session_id}: {e}")
            raise

    @staticmethod
    def get_latest_by_session(session_id: str) -> Optional[AgentTaskEntity]:
        """
        获取会话的最新任务

        Returns:
            最新的 AgentTaskEntity 对象或 None
        """
        sql = """
            SELECT * FROM agent_tasks
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """

        try:
            result = execute_query(sql, (session_id,), fetch_one=True)
            if result:
                return AgentTaskEntity(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get latest task for session {session_id}: {e}")
            raise

    @staticmethod
    def delete_old_tasks(max_age_hours: int = 24) -> int:
        """
        Delete old completed/failed/cancelled tasks

        Returns:
            Number of deleted rows
        """
        sql = """
            DELETE FROM agent_tasks
            WHERE status IN ('completed', 'failed', 'cancelled')
            AND created_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
        """

        try:
            affected_rows = execute_update(sql, (max_age_hours,))
            if affected_rows > 0:
                logger.info(f"Deleted {affected_rows} old agent tasks")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete old tasks: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `agent_tasks` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `task_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'UUID task identifier',
  `session_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Associated session ID',
  `user_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'User ID',
  `world_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'World ID',
  `user_message` longtext COLLATE utf8mb4_unicode_ci COMMENT 'User message content',
  `auth_token` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Authentication token',
  `vendor_id` int DEFAULT NULL COMMENT 'Vendor ID',
  `model_id` int DEFAULT NULL COMMENT 'Model ID',
  `enable_thinking` varchar(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'false' COMMENT 'Thinking mode: true/false/auto',
  `thinking_effort` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT 'medium' COMMENT 'Thinking effort level (low/medium/high)',
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending' COMMENT 'Task status: pending/running/waiting_human/completed/failed/cancelled',
  `progress` float NOT NULL DEFAULT '0' COMMENT 'Task progress 0-1',
  `current_step` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT 'Current step description',
  `result` longtext COLLATE utf8mb4_unicode_ci COMMENT 'Task result (JSON)',
  `error` text COLLATE utf8mb4_unicode_ci COMMENT 'Error message if failed',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Task creation time',
  `started_at` datetime DEFAULT NULL COMMENT 'Task start time',
  `completed_at` datetime DEFAULT NULL COMMENT 'Task completion time',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task_id` (`task_id`),
  KEY `idx_session_id` (`session_id`),
  KEY `idx_user_world` (`user_id`,`world_id`)
) ENGINE=InnoDB
"""