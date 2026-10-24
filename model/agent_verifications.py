"""
Agent Verifications Model - Database operations for agent_verifications table
用于跨进程共享验证请求状态，支持 gunicorn 多 worker 模式
替代内存中的 VerificationRequest + threading.Event 方案
"""
from typing import Optional, Dict, Any
from datetime import datetime
import json

from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class AgentVerificationEntity:
    """Agent verification database entity class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.verification_id = kwargs.get('verification_id')
        self.task_id = kwargs.get('task_id')
        self.verification_type = kwargs.get('verification_type', 'ask_user')
        self.title = kwargs.get('title', '')
        self.description = kwargs.get('description', '')

        # Deserialize options from JSON
        options_json = kwargs.get('options')
        if isinstance(options_json, str) and options_json:
            try:
                self.options = json.loads(options_json)
            except json.JSONDecodeError:
                self.options = []
        else:
            self.options = options_json or []

        # Deserialize context from JSON
        context_json = kwargs.get('context')
        if isinstance(context_json, str) and context_json:
            try:
                self.context = json.loads(context_json)
            except json.JSONDecodeError:
                self.context = {}
        else:
            self.context = context_json or {}

        self.status = kwargs.get('status', 'pending')
        self.created_at = kwargs.get('created_at')

        # Deserialize result from JSON
        result_json = kwargs.get('result')
        if isinstance(result_json, str) and result_json:
            try:
                self.result = json.loads(result_json)
            except json.JSONDecodeError:
                self.result = None
        else:
            self.result = result_json

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for SSE/API output"""
        return {
            'verification_id': self.verification_id,
            'task_id': self.task_id,
            'verification_type': self.verification_type,
            'title': self.title,
            'description': self.description,
            'options': self.options,
            'context': self.context,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class AgentVerificationsModel:
    """Agent verifications database operations"""

    @staticmethod
    def create(
        verification_id: str,
        task_id: str,
        verification_type: str = 'ask_user',
        title: str = '',
        description: str = '',
        options: list = None,
        context: dict = None
    ) -> int:
        """
        Create a new verification request

        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO agent_verifications
            (verification_id, task_id, verification_type, title, description, options, context)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        options_json = json.dumps(options or [], ensure_ascii=False)
        context_json = json.dumps(context or {}, ensure_ascii=False)
        params = (verification_id, task_id, verification_type, title, description, options_json, context_json)

        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created verification with ID: {record_id}, verification_id: {verification_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create verification: {e}")
            raise

    @staticmethod
    def get_by_verification_id(verification_id: str) -> Optional[AgentVerificationEntity]:
        """
        Get verification by verification_id

        Returns:
            AgentVerificationEntity object or None
        """
        sql = "SELECT * FROM agent_verifications WHERE verification_id = %s"

        try:
            result = execute_query(sql, (verification_id,), fetch_one=True)
            if result:
                return AgentVerificationEntity(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get verification {verification_id}: {e}")
            raise

    @staticmethod
    def submit_result(verification_id: str, status: str, result: Dict[str, Any]) -> bool:
        """
        Submit verification result

        Args:
            verification_id: Verification UUID
            status: New status (approved/rejected/cancelled)
            result: Result dict with action and user_input

        Returns:
            True if updated, False if not found or already submitted
        """
        sql = """
            UPDATE agent_verifications
            SET status = %s, result = %s
            WHERE verification_id = %s AND status = 'pending'
        """
        result_json = json.dumps(result, ensure_ascii=False)

        try:
            affected_rows = execute_update(sql, (status, result_json, verification_id))
            if affected_rows > 0:
                logger.info(f"Verification {verification_id} updated to {status}")
                return True
            else:
                # Check if exists but already processed
                existing = AgentVerificationsModel.get_by_verification_id(verification_id)
                if existing and existing.status != 'pending':
                    logger.warning(f"Verification {verification_id} already processed: {existing.status}")
                else:
                    logger.warning(f"Verification {verification_id} not found")
                return False
        except Exception as e:
            logger.error(f"Failed to submit verification {verification_id}: {e}")
            raise

    @staticmethod
    def list_approved_by_session(session_id: str, verification_type: str) -> list:
        """列出某会话里已提交为 approved 的验证。供算力确认门跨进程读取。

        前端三个按钮都会把 approved 写成 true，调用方必须自己解析 result.user_input。
        同时用 task_id 匹配，覆盖还没有会话 id、只能落到任务 id 的旧路径。
        """
        sql = """
            SELECT v.context, v.result
            FROM agent_verifications v
            INNER JOIN agent_tasks t ON t.task_id = v.task_id
            WHERE v.verification_type = %s
              AND v.status = 'approved'
              AND (t.session_id = %s OR v.task_id = %s)
        """
        try:
            rows = execute_query(
                sql,
                (verification_type, session_id, session_id),
                fetch_all=True,
            )
            return rows or []
        except Exception as e:
            logger.error(
                "Failed to list approved verifications for session %s: %s",
                session_id,
                e,
            )
            raise

    @staticmethod
    def get_latest_completed_by_task(
        task_id: str,
        verification_type: str = 'ask_user'
    ) -> Optional[AgentVerificationEntity]:
        """获取指定任务最新已完成的验证请求

        Returns:
            AgentVerificationEntity object or None
        """
        sql = """
            SELECT * FROM agent_verifications
            WHERE task_id = %s AND verification_type = %s AND status = 'approved'
            ORDER BY created_at DESC
            LIMIT 1
        """

        try:
            result = execute_query(sql, (task_id, verification_type), fetch_one=True)
            if result:
                return AgentVerificationEntity(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get latest completed verification for task {task_id}: {e}")
            raise

    @staticmethod
    def get_pending_by_task(task_id: str) -> Optional[AgentVerificationEntity]:
        """
        Get the latest pending verification for a task

        Returns:
            AgentVerificationEntity object or None
        """
        sql = """
            SELECT * FROM agent_verifications
            WHERE task_id = %s AND status = 'pending'
            ORDER BY created_at DESC
            LIMIT 1
        """

        try:
            result = execute_query(sql, (task_id,), fetch_one=True)
            if result:
                return AgentVerificationEntity(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get pending verification for task {task_id}: {e}")
            raise

    @staticmethod
    def delete_old_verifications(max_age_hours: int = 24) -> int:
        """
        Delete old verifications (any status)

        Returns:
            Number of deleted rows
        """
        sql = """
            DELETE FROM agent_verifications
            WHERE created_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
        """

        try:
            affected_rows = execute_update(sql, (max_age_hours,))
            if affected_rows > 0:
                logger.info(f"Deleted {affected_rows} old verifications")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete old verifications: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `agent_verifications` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `verification_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'UUID verification identifier',
  `task_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Associated task ID',
  `verification_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'ask_user' COMMENT 'Type: ask_user',
  `title` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT '' COMMENT 'Verification title',
  `description` text COLLATE utf8mb4_unicode_ci COMMENT 'Verification description / question',
  `options` text COLLATE utf8mb4_unicode_ci COMMENT 'Options list (JSON array)',
  `context` text COLLATE utf8mb4_unicode_ci COMMENT 'Extra context (JSON object)',
  `status` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending' COMMENT 'Status: pending/approved/rejected/cancelled',
  `result` longtext COLLATE utf8mb4_unicode_ci COMMENT 'Result (JSON: {action, user_input})',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation time',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_verification_id` (`verification_id`),
  KEY `idx_task_id` (`task_id`),
  KEY `idx_status` (`status`),
  KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Agent verification requests for cross-process sharing'
"""
