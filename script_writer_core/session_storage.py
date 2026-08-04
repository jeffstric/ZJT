"""
Session Storage - Abstraction layer for chat session persistence
Provides database-backed session storage with optional in-memory caching
"""
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from model.chat_sessions import ChatSessionEntity, ChatSessionsModel
from script_writer_core.chat_session import ChatSession
from config.constant import SessionHistoryConstants

logger = logging.getLogger(__name__)


def _find_safe_preserve_start(msgs: list, desired_start: int) -> int:
    """找到安全的保留起始索引，确保不会将 tool 消息与其前置的 assistant(tool_calls) 拆分。

    从 desired_start 向前搜索，如果 desired_start 指向的是 tool 消息，
    则继续向前直到找到对应的 assistant(tool_calls) 消息。
    """
    start = desired_start
    while start > 0:
        msg = msgs[start]
        role = msg.get("role")
        if role == "tool" or role == "verification":
            start -= 1
        else:
            break
    return start


def truncate_conversation_history(history: list, max_messages: int = None, keep_system: bool = True) -> list:
    """
    截断对话历史，保留系统提示和最近的对话

    Args:
        history: 对话历史列表
        max_messages: 最大消息数量（默认使用配置值）
        keep_system: 是否保留系统提示

    Returns:
        截断后的对话历史
    """
    if max_messages is None:
        max_messages = SessionHistoryConstants.MAX_HISTORY_MESSAGES

    if len(history) <= max_messages:
        return history

    # 分离系统提示和普通消息
    system_messages = [msg for msg in history if msg.get('role') == 'system']
    other_messages = [msg for msg in history if msg.get('role') != 'system']

    # 计算需要保留的普通消息数量
    if keep_system and system_messages:
        # 保留所有系统提示，然后截断普通消息
        max_other_messages = max_messages - len(system_messages)
        if max_other_messages < SessionHistoryConstants.MIN_HISTORY_MESSAGES:
            max_other_messages = SessionHistoryConstants.MIN_HISTORY_MESSAGES
        if len(other_messages) > max_other_messages:
            # 找到安全的截断起始索引，避免拆分 tool_calls/tool 消息组
            desired_start = len(other_messages) - max_other_messages
            safe_start = _find_safe_preserve_start(other_messages, desired_start)
            truncated_other = other_messages[safe_start:]
        else:
            truncated_other = other_messages
        return system_messages + truncated_other
    else:
        # 不保留系统提示，直接截断所有消息
        if len(history) > max_messages:
            desired_start = len(history) - max_messages
            safe_start = _find_safe_preserve_start(history, desired_start)
            return history[safe_start:]
        return history


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
            model_id=entity.model_id,
            text_to_image_model_id=entity.text_to_image_model_id,
            session_type=entity.session_type
        )

        # 会话草稿 text_to_image_model_id 仅挂在 session 对象上，供创建 task 时回退。
        # 不再写回世界级 user_preferences，避免「本对话模型」覆盖「世界默认」。
        if entity.text_to_image_model_id is not None:
            logger.info(
                f"[Session Load] session text_to_image_model_id={entity.text_to_image_model_id} "
                f"for user={entity.user_id}, world={entity.world_id} (session-scoped only)"
            )

        # Restore conversation history
        # PM Agent 在初始化时会自动添加系统提示到 conversation_history
        # 数据库中只保存了用户和助手的对话（不包括 system 消息）
        # 我们需要将数据库中的对话历史追加到 PM Agent 的系统提示后面
        if entity.conversation_history:
            logger.info(f"[Session Load] Restoring {len(entity.conversation_history)} messages from database")
            logger.info(f"[Session Load] PM Agent has {len(session.pm_agent.conversation_history)} messages (system prompt)")
            
            # 将数据库中的历史记录追加到系统提示后面
            session.pm_agent.conversation_history.extend(entity.conversation_history)
            
            logger.info(f"[Session Load] PM Agent conversation_history restored, now has {len(session.pm_agent.conversation_history)} messages")
            
            # 记录恢复的消息角色
            if len(session.pm_agent.conversation_history) > 0:
                roles = [msg.get('role', 'unknown') for msg in session.pm_agent.conversation_history[-5:]]
                logger.info(f"[Session Load] Last 5 message roles: {', '.join(roles)}")
        else:
            logger.info(f"[Session Load] No conversation history to restore, keeping PM Agent's default (system prompt only)")

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
                # 新路径：不再覆盖 conversation_history，消息已在 add_to_history 中逐条写入 chat_messages
                # 只更新元数据（model、expires_at 等）
                logger.info(f"[Session Save] Session {session.session_id} - Saving metadata only (conversation_history is now in chat_messages)")

                # 只更新 model 和 expires_at，不写 conversation_history
                ChatSessionsModel.update_model(
                    session_id=session.session_id,
                    model=session.model,
                    model_id=session.model_id,
                    expires_at=expires_at
                )

                # 轻量更新 expires_at（不触碰 conversation_history）
                ChatSessionsModel.update_metadata(
                    session_id=session.session_id,
                    expires_at=expires_at
                )

                logger.info(f"Session {session.session_id} updated in database (metadata only)")

                # Update cache with the latest session state
                if self.use_cache:
                    with self._lock:
                        self._cache[session.session_id] = (session, datetime.now())
                        logger.info(f"[Session Save] Cache updated after save")
            else:
                # Create new session
                ChatSessionsModel.create(
                    session_id=session.session_id,
                    user_id=session.user_id,
                    world_id=session.world_id,
                    auth_token=session.auth_token,
                    model=session.model,
                    model_id=session.model_id,
                    text_to_image_model_id=session.text_to_image_model_id,
                    conversation_history=[],  # 新路径：不再用旧字段存历史，消息在 chat_messages 表中
                    expires_at=expires_at,
                    session_type=getattr(session, 'session_type', 1)
                )
                logger.info(f"Session {session.session_id} created in database")
                
                # Update cache with the new session
                if self.use_cache:
                    with self._lock:
                        self._cache[session.session_id] = (session, datetime.now())
                        logger.info(f"[Session Save] Cache updated after create")

            # Update session timestamps
            session.updated_at = datetime.now()

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
            ChatSessionsModel.update_tokens(
                session_id=session_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_tokens=cache_creation_tokens,
                cache_read_tokens=cache_read_tokens
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

    def invalidate_cache(self, session_id: str):
        """Remove a specific session from cache"""
        if not self.use_cache:
            return
        with self._lock:
            removed = self._cache.pop(session_id, None)
            if removed:
                logger.info(f"Session {session_id} cache invalidated")

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
