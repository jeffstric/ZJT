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
        truncated_other = other_messages[-max_other_messages:] if len(other_messages) > max_other_messages else other_messages
        return system_messages + truncated_other
    else:
        # 不保留系统提示，直接截断所有消息
        return history[-max_messages:] if len(history) > max_messages else history


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
            text_to_image_model_id=entity.text_to_image_model_id
        )

        # 同步生图模型配置到内存（解决页面刷新/服务重启后配置丢失问题）
        if entity.text_to_image_model_id is not None:
            from api.script_writer import set_text_to_image_model_id
            set_text_to_image_model_id(entity.user_id, entity.world_id, entity.text_to_image_model_id)
            logger.info(f"[Session Load] Synced text_to_image_model_id={entity.text_to_image_model_id} to memory config for user={entity.user_id}, world={entity.world_id}")

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
                # 获取当前历史记录
                current_history = session.get_history()
                logger.info(f"[Session Save] Session {session.session_id} - Current history has {len(current_history)} messages")
                
                # 过滤掉 system 消息（系统提示在每次初始化时重新生成，不需要保存）
                filtered_history = [msg for msg in current_history if msg.get('role') != 'system']
                logger.info(f"[Session Save] After filtering system messages: {len(filtered_history)} messages")
                
                # 记录最后几条消息的角色
                if filtered_history:
                    last_messages = filtered_history[-3:]
                    roles_summary = [f"{msg.get('role', 'unknown')}" for msg in last_messages]
                    logger.info(f"[Session Save] Last {len(last_messages)} message roles: {', '.join(roles_summary)}")
                
                # 截断对话历史以避免无限增长
                truncated_history = truncate_conversation_history(
                    filtered_history,
                    max_messages=SessionHistoryConstants.MAX_HISTORY_MESSAGES,
                    keep_system=False  # 已经过滤掉了 system 消息
                )
                
                logger.info(f"[Session Save] After truncation: {len(truncated_history)} messages")
                
                # Update existing session (conversation history only, tokens are cumulative in DB)
                ChatSessionsModel.update_conversation_history(
                    session_id=session.session_id,
                    conversation_history=truncated_history,
                    update_tokens=False,  # Token stats are cumulative, don't add delta
                    expires_at=expires_at  # Update expiration time to extend session validity
                )
                # Also update the model if changed
                ChatSessionsModel.update_model(
                    session_id=session.session_id,
                    model=session.model,
                    model_id=session.model_id,
                    expires_at=expires_at
                )
                logger.info(f"Session {session.session_id} updated in database")
                
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
                    conversation_history=session.get_history(),
                    expires_at=expires_at
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
