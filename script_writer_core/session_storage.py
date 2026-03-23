"""
Session Storage - Abstraction layer for chat session persistence
Provides database-backed session storage with optional in-memory caching
"""
import threading
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from .chat_session import ChatSession
from model.chat_sessions import ChatSessionsModel, ChatSessionEntity
import logging

logger = logging.getLogger(__name__)


class SessionStorage:
    """
    Session storage abstraction layer with database backend and optional cache

    This class manages the persistence of ChatSession objects to the database,
    with an optional in-memory cache for improved performance.
    """

    def __init__(self, use_cache: bool = True, cache_ttl: int = 300):
        """
        Initialize session storage

        Args:
            use_cache: Enable in-memory caching (default: True)
            cache_ttl: Cache TTL in seconds (default: 5 minutes)
        """
        self.use_cache = use_cache
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, tuple[ChatSession, datetime]] = {}
        self._lock = threading.RLock()

    def _is_cache_valid(self, cached_time: datetime) -> bool:
        """Check if cache entry is still valid"""
        return (datetime.now() - cached_time).total_seconds() < self.cache_ttl

    def _deserialize_session(
        self,
        entity: ChatSessionEntity,
        task_manager,
        file_manager,
        tool_executor,
        agents_config: dict
    ) -> ChatSession:
        """
        Deserialize database entity to ChatSession object

        Args:
            entity: ChatSessionEntity from database
            task_manager: TaskManager instance for session
            file_manager: FileManager instance for session
            tool_executor: ToolExecutor instance for session
            agents_config: Agents configuration dict

        Returns:
            Reconstructed ChatSession object
        """
        # Create ChatSession instance
        session = ChatSession(
            session_id=entity.session_id,
            task_manager=task_manager,
            file_manager=file_manager,
            tool_executor=tool_executor,
            agents_config=agents_config,
            user_id=entity.user_id,
            world_id=entity.world_id,
            auth_token=entity.auth_token or '',
            model=entity.model,
            model_id=entity.model_id
        )

        # Restore conversation history
        if entity.conversation_history:
            session.pm_agent.conversation_history = entity.conversation_history

        # Restore timestamps
        session.created_at = entity.created_at
        session.updated_at = entity.updated_at

        # Restore token statistics
        session.total_input_tokens = entity.total_input_tokens
        session.total_output_tokens = entity.total_output_tokens
        session.total_cache_creation_tokens = entity.total_cache_creation_tokens
        session.total_cache_read_tokens = entity.total_cache_read_tokens

        logger.debug(f"Deserialized session {entity.session_id} from database")
        return session

    def load_session(
        self,
        session_id: str,
        task_manager,
        file_manager,
        tool_executor,
        agents_config: dict
    ) -> Optional[ChatSession]:
        """
        Load session from database (with optional cache)

        Args:
            session_id: Session identifier
            task_manager: TaskManager instance
            file_manager: FileManager instance
            tool_executor: ToolExecutor instance
            agents_config: Agents configuration dict

        Returns:
            ChatSession object or None if not found
        """
        # Check cache first
        if self.use_cache:
            with self._lock:
                if session_id in self._cache:
                    cached_session, cached_time = self._cache[session_id]
                    if self._is_cache_valid(cached_time):
                        logger.debug(f"Session {session_id} loaded from cache")
                        return cached_session

        # Load from database
        entity = ChatSessionsModel.get_by_session_id(session_id)
        if not entity:
            logger.warning(f"Session {session_id} not found in database")
            return None

        # Deserialize to ChatSession
        session = self._deserialize_session(
            entity, task_manager, file_manager, tool_executor, agents_config
        )

        # Update cache
        if self.use_cache:
            with self._lock:
                self._cache[session_id] = (session, datetime.now())

        logger.info(f"Session {session_id} loaded from database")
        return session

    def save_session(
        self,
        session: ChatSession,
        expires_hours: int = 24
    ) -> bool:
        """
        Save or update session to database

        Args:
            session: ChatSession object to save
            expires_hours: Hours until session expires (0 = never expires)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if session exists
            existing = ChatSessionsModel.get_by_session_id(session.session_id)

            # Calculate expiration time
            expires_at = None
            if expires_hours > 0:
                expires_at = datetime.now() + timedelta(hours=expires_hours)

            if existing:
                # Update existing session (conversation history only, tokens are cumulative in DB)
                ChatSessionsModel.update_conversation_history(
                    session_id=session.session_id,
                    conversation_history=session.get_history(),
                    update_tokens=False,  # Token stats are cumulative, don't add delta
                    expires_at=expires_at  # Update expiration time to extend session validity
                )
                # Also update the model if changed
                ChatSessionsModel.update_model(session.session_id, session.model, session.model_id, expires_at=expires_at)
                logger.info(f"Session {session.session_id} updated in database")
            else:
                # Create new session
                ChatSessionsModel.create(
                    session_id=session.session_id,
                    user_id=session.user_id,
                    world_id=session.world_id,
                    auth_token=session.auth_token,
                    model=session.model,
                    model_id=session.model_id,
                    conversation_history=session.get_history(),
                    expires_at=expires_at
                )
                logger.info(f"Session {session.session_id} created in database")

            # Update cache
            if self.use_cache:
                with self._lock:
                    self._cache[session.session_id] = (session, datetime.now())

            return True

        except Exception as e:
            logger.error(f"Failed to save session {session.session_id}: {e}")
            return False

    def update_session_tokens(
        self,
        session_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0
    ) -> bool:
        """
        Update token statistics for a session without loading it

        Args:
            session_id: Session identifier
            input_tokens: Input tokens to add
            output_tokens: Output tokens to add
            cache_creation_tokens: Cache creation tokens to add
            cache_read_tokens: Cache read tokens to add

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current history to update
            entity = ChatSessionsModel.get_by_session_id(session_id)
            if not entity:
                logger.warning(f"Session {session_id} not found for token update")
                return False

            ChatSessionsModel.update_conversation_history(
                session_id=session_id,
                conversation_history=entity.conversation_history,
                update_tokens=True,
                token_stats={
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'cache_creation_tokens': cache_creation_tokens,
                    'cache_read_tokens': cache_read_tokens
                }
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update tokens for session {session_id}: {e}")
            return False

    def delete_session(self, session_id: str) -> bool:
        """
        Delete session from database (soft delete)

        Args:
            session_id: Session identifier

        Returns:
            True if successful, False otherwise
        """
        try:
            ChatSessionsModel.soft_delete(session_id)

            # Remove from cache
            if self.use_cache:
                with self._lock:
                    self._cache.pop(session_id, None)

            logger.info(f"Session {session_id} deleted")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False

    def clear_cache(self):
        """Clear all cached sessions"""
        with self._lock:
            self._cache.clear()
        logger.info("Session cache cleared")

    def cleanup_stale_cache(self):
        """Remove expired cache entries"""
        if not self.use_cache:
            return 0

        with self._lock:
            now = datetime.now()
            expired_keys = [
                session_id
                for session_id, (_, cached_time) in self._cache.items()
                if not self._is_cache_valid(cached_time)
            ]
            for key in expired_keys:
                self._cache.pop(key, None)

        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} stale cache entries")
        return len(expired_keys)

    def get_cached_sessions(self) -> list:
        """
        Get list of currently cached session IDs

        Returns:
            List of session IDs in cache
        """
        if not self.use_cache:
            return []

        with self._lock:
            return list(self._cache.keys())

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics

        Returns:
            Dictionary with cache stats
        """
        if not self.use_cache:
            return {
                'enabled': False,
                'size': 0,
                'ttl': self.cache_ttl
            }

        with self._lock:
            now = datetime.now()
            valid_count = sum(
                1 for _, cached_time in self._cache.values()
                if self._is_cache_valid(cached_time)
            )
            return {
                'enabled': True,
                'size': len(self._cache),
                'valid_count': valid_count,
                'ttl': self.cache_ttl
            }
