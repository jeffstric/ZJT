"""
Chat Sessions Model - Database operations for chat_sessions table
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class ChatSessionEntity:
    """Chat session database entity class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.session_id = kwargs.get('session_id')
        self.user_id = kwargs.get('user_id')
        self.world_id = kwargs.get('world_id')
        self.auth_token = kwargs.get('auth_token', '')
        self.model = kwargs.get('model', 'gemini-3-flash-preview')
        self.model_id = kwargs.get('model_id')

        # Deserialize conversation_history from JSON
        history_json = kwargs.get('conversation_history', '[]')
        if isinstance(history_json, str):
            try:
                self.conversation_history = json.loads(history_json)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse conversation_history for session {kwargs.get('session_id')}, using empty list")
                self.conversation_history = []
        else:
            self.conversation_history = history_json if history_json else []

        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
        self.expires_at = kwargs.get('expires_at')

        self.total_input_tokens = kwargs.get('total_input_tokens', 0)
        self.total_output_tokens = kwargs.get('total_output_tokens', 0)
        self.total_cache_creation_tokens = kwargs.get('total_cache_creation_tokens', 0)
        self.total_cache_read_tokens = kwargs.get('total_cache_read_tokens', 0)
        self.is_active = kwargs.get('is_active', 1)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, serializing conversation_history to JSON string"""
        return {
            'id': self.id,
            'session_id': self.session_id,
            'user_id': self.user_id,
            'world_id': self.world_id,
            'auth_token': self.auth_token,
            'model': self.model,
            'model_id': self.model_id,
            'conversation_history': json.dumps(self.conversation_history, ensure_ascii=False),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'total_input_tokens': self.total_input_tokens,
            'total_output_tokens': self.total_output_tokens,
            'total_cache_creation_tokens': self.total_cache_creation_tokens,
            'total_cache_read_tokens': self.total_cache_read_tokens,
            'is_active': self.is_active
        }


class ChatSessionsModel:
    """Chat sessions database operations"""

    @staticmethod
    def create(
        session_id: str,
        user_id: str,
        world_id: str,
        auth_token: str = '',
        model: str = 'gemini-3-flash-preview',
        model_id: Optional[int] = None,
        conversation_history: list = None,
        expires_at: Optional[datetime] = None
    ) -> int:
        """
        Create a new chat session

        Args:
            session_id: Unique session identifier (UUID)
            user_id: User ID
            world_id: World ID
            auth_token: Authentication token
            model: AI model name
            model_id: Model ID from vendor
            conversation_history: Initial conversation history (default: empty list)
            expires_at: Session expiration time (None = never expires)

        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO chat_sessions
            (session_id, user_id, world_id, auth_token, model, model_id,
             conversation_history, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        history_json = json.dumps(conversation_history or [], ensure_ascii=False)
        params = (session_id, user_id, world_id, auth_token, model,
                  model_id, history_json, expires_at)

        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created chat session with ID: {record_id}, session_id: {session_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create chat session: {e}")
            raise

    @staticmethod
    def get_by_session_id(session_id: str) -> Optional[ChatSessionEntity]:
        """
        Get session by session_id

        Args:
            session_id: Session identifier

        Returns:
            ChatSessionEntity object or None
        """
        sql = "SELECT * FROM chat_sessions WHERE session_id = %s AND is_active = 1"

        try:
            result = execute_query(sql, (session_id,), fetch_one=True)
            if result:
                return ChatSessionEntity(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get session {session_id}: {e}")
            raise

    @staticmethod
    def list_by_user(
        user_id: str,
        world_id: Optional[str] = None,
        active_only: bool = True,
        limit: int = 100
    ) -> List[ChatSessionEntity]:
        """
        List sessions by user

        Args:
            user_id: User ID
            world_id: Optional world ID filter
            active_only: Only return active sessions
            limit: Maximum number of sessions to return

        Returns:
            List of ChatSessionEntity objects
        """
        if world_id:
            sql = """
                SELECT * FROM chat_sessions
                WHERE user_id = %s AND world_id = %s
                AND is_active = %s
                ORDER BY updated_at DESC
                LIMIT %s
            """
            params = (user_id, world_id, 1 if active_only else 0, limit)
        else:
            sql = """
                SELECT * FROM chat_sessions
                WHERE user_id = %s AND is_active = %s
                ORDER BY updated_at DESC
                LIMIT %s
            """
            params = (user_id, 1 if active_only else 0, limit)

        try:
            results = execute_query(sql, params, fetch_all=True)
            return [ChatSessionEntity(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to list sessions for user {user_id}: {e}")
            raise

    @staticmethod
    def list_all(
        active_only: bool = True,
        limit: int = 100
    ) -> List[ChatSessionEntity]:
        """
        List all sessions

        Args:
            active_only: Only return active sessions
            limit: Maximum number of sessions to return

        Returns:
            List of ChatSessionEntity objects
        """
        sql = """
            SELECT * FROM chat_sessions
            WHERE is_active = %s
            ORDER BY updated_at DESC
            LIMIT %s
        """
        params = (1 if active_only else 0, limit)

        try:
            results = execute_query(sql, params, fetch_all=True)
            return [ChatSessionEntity(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to list all sessions: {e}")
            raise

    @staticmethod
    def update_conversation_history(
        session_id: str,
        conversation_history: list,
        update_tokens: bool = False,
        token_stats: Optional[Dict[str, int]] = None
    ) -> int:
        """
        Update conversation history and optionally token statistics

        Args:
            session_id: Session identifier
            conversation_history: New conversation history
            update_tokens: Whether to update token statistics
            token_stats: Dictionary with token deltas (input_tokens, output_tokens, etc.)

        Returns:
            Number of affected rows
        """
        history_json = json.dumps(conversation_history, ensure_ascii=False)

        if update_tokens and token_stats:
            sql = """
                UPDATE chat_sessions
                SET conversation_history = %s,
                    updated_at = NOW(),
                    total_input_tokens = total_input_tokens + %s,
                    total_output_tokens = total_output_tokens + %s,
                    total_cache_creation_tokens = total_cache_creation_tokens + %s,
                    total_cache_read_tokens = total_cache_read_tokens + %s
                WHERE session_id = %s AND is_active = 1
            """
            params = (
                history_json,
                token_stats.get('input_tokens', 0),
                token_stats.get('output_tokens', 0),
                token_stats.get('cache_creation_tokens', 0),
                token_stats.get('cache_read_tokens', 0),
                session_id
            )
        else:
            sql = """
                UPDATE chat_sessions
                SET conversation_history = %s, updated_at = NOW()
                WHERE session_id = %s AND is_active = 1
            """
            params = (history_json, session_id)

        try:
            affected_rows = execute_update(sql, params)
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update conversation history for {session_id}: {e}")
            raise

    @staticmethod
    def update_model(session_id: str, model: str, model_id: Optional[int] = None) -> int:
        """
        Update session model

        Args:
            session_id: Session identifier
            model: New model name
            model_id: New model ID

        Returns:
            Number of affected rows
        """
        sql = """
            UPDATE chat_sessions
            SET model = %s, model_id = %s, updated_at = NOW()
            WHERE session_id = %s AND is_active = 1
        """
        params = (model, model_id, session_id)

        try:
            affected_rows = execute_update(sql, params)
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update model for {session_id}: {e}")
            raise

    @staticmethod
    def clear_history(session_id: str) -> int:
        """
        Clear conversation history

        Args:
            session_id: Session identifier

        Returns:
            Number of affected rows
        """
        empty_history = json.dumps([], ensure_ascii=False)
        sql = """
            UPDATE chat_sessions
            SET conversation_history = %s, updated_at = NOW()
            WHERE session_id = %s AND is_active = 1
        """
        params = (empty_history, session_id)

        try:
            affected_rows = execute_update(sql, params)
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to clear history for {session_id}: {e}")
            raise

    @staticmethod
    def soft_delete(session_id: str) -> int:
        """
        Soft delete session (set is_active = 0)

        Args:
            session_id: Session identifier

        Returns:
            Number of affected rows
        """
        sql = "UPDATE chat_sessions SET is_active = 0, updated_at = NOW() WHERE session_id = %s"

        try:
            affected_rows = execute_update(sql, (session_id,))
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            raise

    @staticmethod
    def delete_expired_sessions(before_date: Optional[datetime] = None) -> int:
        """
        Soft delete expired sessions

        Args:
            before_date: Cutoff date for expiration (default: now)

        Returns:
            Number of affected rows
        """
        if before_date is None:
            before_date = datetime.now()

        sql = """
            UPDATE chat_sessions
            SET is_active = 0, updated_at = NOW()
            WHERE expires_at <= %s AND is_active = 1
        """

        try:
            affected_rows = execute_update(sql, (before_date,))
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete expired sessions: {e}")
            raise

    @staticmethod
    def count_active_sessions() -> int:
        """
        Count total active sessions

        Returns:
            Number of active sessions
        """
        sql = "SELECT COUNT(*) as count FROM chat_sessions WHERE is_active = 1"

        try:
            result = execute_query(sql, fetch_one=True)
            return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to count active sessions: {e}")
            raise
