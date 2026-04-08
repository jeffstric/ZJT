"""
Agent Task Messages Model - Database operations for agent_task_messages table
用于存储任务产生的流式消息，供 SSE 接口轮询读取
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class AgentTaskMessageEntity:
    """Agent task message database entity class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.task_id = kwargs.get('task_id')
        self.message_type = kwargs.get('message_type', 'message')

        # Deserialize content from JSON
        content_json = kwargs.get('content')
        if isinstance(content_json, str) and content_json:
            try:
                self.content = json.loads(content_json)
            except json.JSONDecodeError:
                self.content = {'raw': content_json}
        else:
            self.content = content_json or {}

        self.created_at = kwargs.get('created_at')

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for SSE output"""
        result = {
            'id': self.id,
            'type': self.message_type,
            **self.content
        }
        return result


class AgentTaskMessagesModel:
    """Agent task messages database operations"""

    @staticmethod
    def create(
        task_id: str,
        message_type: str,
        content: Dict[str, Any]
    ) -> int:
        """
        Create a new task message

        Args:
            task_id: Task identifier
            message_type: Message type (message/progress/done/error/status/heartbeat/connected)
            content: Message content dict

        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO agent_task_messages
            (task_id, message_type, content)
            VALUES (%s, %s, %s)
        """
        content_json = json.dumps(content, ensure_ascii=False)
        params = (task_id, message_type, content_json)

        try:
            record_id = execute_insert(sql, params)
            logger.debug(f"Created task message with ID: {record_id}, task_id: {task_id}, type: {message_type}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create task message: {e}")
            raise

    @staticmethod
    def get_messages_after(
        task_id: str,
        after_id: int = 0,
        limit: int = 100
    ) -> List[AgentTaskMessageEntity]:
        """
        Get messages for a task after a specific message ID

        Args:
            task_id: Task identifier
            after_id: Only return messages with ID > after_id
            limit: Maximum number of messages to return

        Returns:
            List of AgentTaskMessageEntity objects
        """
        sql = """
            SELECT * FROM agent_task_messages
            WHERE task_id = %s AND id > %s
            ORDER BY id ASC
            LIMIT %s
        """

        try:
            results = execute_query(sql, (task_id, after_id, limit), fetch_all=True)
            return [AgentTaskMessageEntity(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get messages for task {task_id}: {e}")
            raise

    @staticmethod
    def get_latest_message(task_id: str) -> Optional[AgentTaskMessageEntity]:
        """
        Get the latest message for a task

        Returns:
            AgentTaskMessageEntity object or None
        """
        sql = """
            SELECT * FROM agent_task_messages
            WHERE task_id = %s
            ORDER BY id DESC
            LIMIT 1
        """

        try:
            result = execute_query(sql, (task_id,), fetch_one=True)
            if result:
                return AgentTaskMessageEntity(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get latest message for task {task_id}: {e}")
            raise

    @staticmethod
    def count_messages(task_id: str) -> int:
        """
        Count messages for a task

        Returns:
            Number of messages
        """
        sql = "SELECT COUNT(*) as count FROM agent_task_messages WHERE task_id = %s"

        try:
            result = execute_query(sql, (task_id,), fetch_one=True)
            return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to count messages for task {task_id}: {e}")
            raise

    @staticmethod
    def delete_by_task_id(task_id: str) -> int:
        """
        Delete all messages for a task

        Returns:
            Number of deleted rows
        """
        sql = "DELETE FROM agent_task_messages WHERE task_id = %s"

        try:
            affected_rows = execute_update(sql, (task_id,))
            if affected_rows > 0:
                logger.debug(f"Deleted {affected_rows} messages for task {task_id}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete messages for task {task_id}: {e}")
            raise

    @staticmethod
    def delete_old_messages(max_age_hours: int = 24) -> int:
        """
        Delete old messages

        Returns:
            Number of deleted rows
        """
        sql = """
            DELETE FROM agent_task_messages
            WHERE created_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
        """

        try:
            affected_rows = execute_update(sql, (max_age_hours,))
            if affected_rows > 0:
                logger.info(f"Deleted {affected_rows} old task messages")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete old messages: {e}")
            raise
