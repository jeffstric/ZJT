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
        self.session_type = kwargs.get('session_type', 1)
        self.title = kwargs.get('title', None)
        self.auth_token = kwargs.get('auth_token', '')
        self.model = kwargs.get('model', 'deepseek-v4-flash')
        self.model_id = kwargs.get('model_id')
        self.text_to_image_model_id = kwargs.get('text_to_image_model_id')

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
            'session_type': self.session_type,
            'title': self.title,
            'auth_token': self.auth_token,
            'model': self.model,
            'model_id': self.model_id,
            'text_to_image_model_id': self.text_to_image_model_id,
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
        model: str = 'deepseek-v4-flash',
        model_id: Optional[int] = None,
        text_to_image_model_id: Optional[int] = None,
        conversation_history: list = None,
        expires_at: Optional[datetime] = None,
        session_type: int = 1
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
            text_to_image_model_id: Text-to-image model task ID
            conversation_history: Initial conversation history (default: empty list)
            expires_at: Session expiration time (None = never expires)
            session_type: Session type (1=script writer, 2=marketing agent)

        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO chat_sessions
            (session_id, user_id, world_id, session_type, auth_token, model, model_id,
             text_to_image_model_id, conversation_history, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        history_json = json.dumps(conversation_history or [], ensure_ascii=False)
        params = (session_id, user_id, world_id, session_type, auth_token, model,
                  model_id, text_to_image_model_id, history_json, expires_at)

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
        limit: int = 100,
        session_type: Optional[int] = None
    ) -> List[ChatSessionEntity]:
        """
        List sessions by user

        Args:
            user_id: User ID
            world_id: Optional world ID filter
            active_only: Only return active sessions
            limit: Maximum number of sessions to return
            session_type: Optional session type filter (1=script, 2=marketing)

        Returns:
            List of ChatSessionEntity objects
        """
        conditions = ["user_id = %s", "is_active = %s"]
        params = [user_id, 1 if active_only else 0]

        if world_id:
            conditions.append("world_id = %s")
            params.append(world_id)

        if session_type is not None:
            conditions.append("session_type = %s")
            params.append(session_type)

        params.append(limit)
        sql = f"""
            SELECT * FROM chat_sessions
            WHERE {' AND '.join(conditions)}
            ORDER BY updated_at DESC
            LIMIT %s
        """

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
        token_stats: Optional[Dict[str, int]] = None,
        expires_at: Optional[datetime] = None
    ) -> int:
        """
        Update conversation history and optionally token statistics

        Args:
            session_id: Session identifier
            conversation_history: New conversation history
            update_tokens: Whether to update token statistics
            token_stats: Dictionary with token deltas (input_tokens, output_tokens, etc.)
            expires_at: New expiration time (optional, updates if provided)

        Returns:
            Number of affected rows
        """
        history_json = json.dumps(conversation_history, ensure_ascii=False)

        if update_tokens and token_stats:
            if expires_at:
                sql = """
                    UPDATE chat_sessions
                    SET conversation_history = %s,
                        updated_at = NOW(),
                        total_input_tokens = total_input_tokens + %s,
                        total_output_tokens = total_output_tokens + %s,
                        total_cache_creation_tokens = total_cache_creation_tokens + %s,
                        total_cache_read_tokens = total_cache_read_tokens + %s,
                        expires_at = %s
                    WHERE session_id = %s AND is_active = 1
                """
                params = (
                    history_json,
                    token_stats.get('input_tokens', 0),
                    token_stats.get('output_tokens', 0),
                    token_stats.get('cache_creation_tokens', 0),
                    token_stats.get('cache_read_tokens', 0),
                    expires_at,
                    session_id
                )
            else:
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
            if expires_at:
                sql = """
                    UPDATE chat_sessions
                    SET conversation_history = %s, updated_at = NOW(), expires_at = %s
                    WHERE session_id = %s AND is_active = 1
                """
                params = (history_json, expires_at, session_id)
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
    def update_model(session_id: str, model: Optional[str] = None, model_id: Optional[int] = None, text_to_image_model_id: Optional[int] = None, expires_at: Optional[datetime] = None) -> int:
        """
        Update session model

        Args:
            session_id: Session identifier
            model: New model name (optional, if None keeps existing value)
            model_id: New model ID (optional)
            text_to_image_model_id: New text-to-image model task ID (optional)
            expires_at: New expiration time (optional, updates if provided)

        Returns:
            Number of affected rows
        """
        # 构建动态 SQL，只更新提供的字段
        update_fields = []
        params = []

        if model is not None:
            update_fields.append("model = %s")
            params.append(model)

        if model_id is not None:
            update_fields.append("model_id = %s")
            params.append(model_id)

        if text_to_image_model_id is not None:
            update_fields.append("text_to_image_model_id = %s")
            params.append(text_to_image_model_id)

        if not update_fields:
            logger.warning(f"No fields to update for session {session_id}")
            return 0

        update_fields.append("updated_at = NOW()")

        if expires_at:
            update_fields.append("expires_at = %s")
            params.append(expires_at)

        params.append(session_id)

        sql = f"""
            UPDATE chat_sessions
            SET {', '.join(update_fields)}
            WHERE session_id = %s AND is_active = 1
        """

        try:
            affected_rows = execute_update(sql, tuple(params))
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update model for {session_id}: {e}")
            raise

    @staticmethod
    def update_metadata(session_id: str, expires_at: Optional[datetime] = None) -> int:
        """
        轻量元数据更新（仅 expires_at），不触碰 conversation_history。
        供 session_storage.save_session 在新消息路径下使用。

        Args:
            session_id: Session identifier
            expires_at: New expiration time (optional)

        Returns:
            Number of affected rows
        """
        update_fields = ["updated_at = NOW()"]
        params = []

        if expires_at:
            update_fields.append("expires_at = %s")
            params.append(expires_at)

        if len(update_fields) == 1:
            # 只有 updated_at，无实质更新
            return 0

        params.append(session_id)
        sql = f"""
            UPDATE chat_sessions
            SET {', '.join(update_fields)}
            WHERE session_id = %s AND is_active = 1
        """

        try:
            return execute_update(sql, tuple(params))
        except Exception as e:
            logger.error(f"Failed to update metadata for {session_id}: {e}")
            raise

    @staticmethod
    def update_tokens(
        session_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0
    ) -> int:
        """
        轻量 token 统计更新，不触碰 conversation_history。
        供 session_storage.update_session_tokens 在新消息路径下使用。

        Args:
            session_id: Session identifier
            input_tokens: Input tokens to add
            output_tokens: Output tokens to add
            cache_creation_tokens: Cache creation tokens to add
            cache_read_tokens: Cache read tokens to add

        Returns:
            Number of affected rows
        """
        sql = """
            UPDATE chat_sessions
            SET updated_at = NOW(),
                total_input_tokens = total_input_tokens + %s,
                total_output_tokens = total_output_tokens + %s,
                total_cache_creation_tokens = total_cache_creation_tokens + %s,
                total_cache_read_tokens = total_cache_read_tokens + %s
            WHERE session_id = %s AND is_active = 1
        """
        params = (
            input_tokens, output_tokens,
            cache_creation_tokens, cache_read_tokens,
            session_id
        )
        try:
            return execute_update(sql, params)
        except Exception as e:
            logger.error(f"Failed to update tokens for {session_id}: {e}")
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
    def update_title(session_id: str, title: str) -> int:
        """
        Update session title

        Args:
            session_id: Session identifier
            title: New title

        Returns:
            Number of affected rows
        """
        sql = "UPDATE chat_sessions SET title = %s, updated_at = NOW() WHERE session_id = %s"
        try:
            affected_rows = execute_update(sql, (title[:100], session_id))
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update title for session {session_id}: {e}")
            raise

    @staticmethod
    def soft_delete(session_id: str, session_type: Optional[int] = None) -> int:
        """
        Soft delete session (set is_active = 0)

        Args:
            session_id: Session identifier
            session_type: Session type (if known, avoids extra query for cleanup)

        Returns:
            Number of affected rows
        """
        # 如果未传 session_type，先查询以判断是否需要清理文件
        if session_type is None:
            try:
                check_sql = "SELECT session_type FROM chat_sessions WHERE session_id = %s AND is_active = 1"
                result = execute_query(check_sql, (session_id,), fetch_one=True)
                if result:
                    session_type = result.get('session_type')
            except Exception:
                pass

        sql = "UPDATE chat_sessions SET is_active = 0, updated_at = NOW() WHERE session_id = %s"

        try:
            affected_rows = execute_update(sql, (session_id,))

            # 营销智能体 session 需要清理关联文件
            if affected_rows > 0 and session_type == 2:
                ChatSessionsModel._cleanup_marketing_files([session_id])

            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            raise

    @staticmethod
    def get_expired_session_ids(before_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        获取即将被删除的过期 session 的 session_id 和 session_type

        Args:
            before_date: 截止时间（默认: 当前时间）

        Returns:
            包含 session_id 和 session_type 的字典列表
        """
        if before_date is None:
            before_date = datetime.now()

        sql = """
            SELECT session_id, session_type FROM chat_sessions
            WHERE expires_at <= %s AND is_active = 1
        """

        try:
            results = execute_query(sql, (before_date,), fetch_all=True)
            return results if results else []
        except Exception as e:
            logger.error(f"[DB] Failed to get expired session ids: {e}")
            raise

    @staticmethod
    def session_exists(session_id: str) -> bool:
        """
        检查 session 是否存在于数据库中（包括已标记为 inactive 的）

        Args:
            session_id: Session identifier

        Returns:
            True if session exists
        """
        sql = "SELECT 1 AS cnt FROM chat_sessions WHERE session_id = %s LIMIT 1"
        try:
            result = execute_query(sql, (session_id,), fetch_one=True)
            return result is not None
        except Exception as e:
            logger.error(f"[DB] Failed to check session existence for {session_id}: {e}")
            raise  # 出错时向上抛出，由调用方决定如何处理

    @staticmethod
    def delete_expired_sessions(before_date: Optional[datetime] = None) -> int:
        """
        Delete expired sessions (hard delete)

        Args:
            before_date: Cutoff date for expiration (default: now)

        Returns:
            Number of affected rows
        """
        if before_date is None:
            before_date = datetime.now()

        try:
            # 先查出即将被删除的 session_id 和 session_type
            expired_sessions = ChatSessionsModel.get_expired_session_ids(before_date)
            session_ids_to_cleanup = [
                s['session_id'] for s in expired_sessions if s.get('session_type') == 2
            ]

            # 先查询有多少条符合条件的记录
            check_sql = "SELECT COUNT(*) as count FROM chat_sessions WHERE expires_at <= %s AND is_active = 1"
            check_result = execute_query(check_sql, (before_date,), fetch_one=True)
            if check_result:
                logger.info(f"[DB] Found {check_result['count']} sessions matching criteria")
            else:
                logger.warning(f"[DB] Query returned no results")

            sql = """
                DELETE FROM chat_sessions
                WHERE expires_at <= %s AND is_active = 1
            """
            affected_rows = execute_update(sql, (before_date,))
            logger.info(f"[DB] Deleted {affected_rows} expired sessions")

            # 清理营销 session 对应的本地文件和 CDN 文件
            if session_ids_to_cleanup:
                ChatSessionsModel._cleanup_marketing_files(session_ids_to_cleanup)

            return affected_rows
        except Exception as e:
            logger.error(f"[DB] Failed to delete expired sessions: {e}")
            raise

    @staticmethod
    def _cleanup_marketing_files(session_ids: List[str]):
        """
        清理营销 session 对应的本地文件目录和 CDN 文件

        清理范围:
        - 本地: upload/marketing/pic/{session_id}/
        - 本地: upload/marketing/video/{session_id}/
        - 本地: upload/marketing/audio/{session_id}/
        - CDN: marketing/{session_id}/ 前缀下的所有文件

        Args:
            session_ids: 需要清理的 session_id 列表
        """
        import os
        import shutil
        import asyncio

        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        marketing_base = os.path.join(app_dir, 'upload', 'marketing')
        sub_dirs = ['pic', 'video', 'audio']

        # 1. 清理本地文件目录
        local_cleaned = 0
        for sid in session_ids:
            for sub in sub_dirs:
                session_dir = os.path.join(marketing_base, sub, sid)
                if os.path.isdir(session_dir):
                    try:
                        shutil.rmtree(session_dir)
                        local_cleaned += 1
                        logger.info(f"[Cleanup] 已清理本地目录: {sub}/{sid}")
                    except Exception as e:
                        logger.error(f"[Cleanup] 清理本地目录失败: {sub}/{sid}, error={e}")

        if local_cleaned > 0:
            logger.info(f"[Cleanup] 共清理 {local_cleaned} 个本地目录")

        # 2. 清理 CDN 文件（异步操作，在新事件循环或已有循环中执行）
        ChatSessionsModel._cleanup_cdn_files(session_ids)

    @staticmethod
    def _cleanup_cdn_files(session_ids: List[str]):
        """
        清理 CDN 上 marketing/{session_id}/ 前缀下的所有文件

        Args:
            session_ids: 需要清理 CDN 文件的 session_id 列表
        """
        import asyncio
        from config.config_util import get_dynamic_config_value

        # 提前判断：未开启 CDN 或无七牛云配置时直接跳过
        auto_upload = get_dynamic_config_value('server', 'auto_upload_to_cdn', default=False)
        if not auto_upload:
            return
        access_key = get_dynamic_config_value('file_storage', 'qiniu_long_term', 'access_key')
        if not access_key:
            return

        async def _do_cleanup():
            try:
                from config.config_util import get_config

                from utils.file_storage.factory import get_file_storage
                storage = get_file_storage(get_config())

                total_deleted = 0
                for sid in session_ids:
                    cdn_prefix = f"marketing/{sid}/"
                    try:
                        deleted = await storage.delete_by_prefix(cdn_prefix)
                        if deleted > 0:
                            total_deleted += deleted
                            logger.info(f"[Cleanup] 已清理 CDN 文件: prefix={cdn_prefix}, count={deleted}")
                    except Exception as e:
                        logger.error(f"[Cleanup] 清理 CDN 文件失败: prefix={cdn_prefix}, error={e}")

                if total_deleted > 0:
                    logger.info(f"[Cleanup] 共清理 {total_deleted} 个 CDN 文件")
            except Exception as e:
                logger.error(f"[Cleanup] CDN 清理总体异常: {e}")

        try:
            loop = asyncio.get_running_loop()
            # 已在异步上下文中，创建任务
            loop.create_task(_do_cleanup())
        except RuntimeError:
            # 不在异步上下文中（如定时任务线程），创建新事件循环执行
            try:
                asyncio.run(_do_cleanup())
            except Exception as e:
                logger.error(f"[Cleanup] 无法执行 CDN 清理: {e}")

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


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `chat_sessions` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `session_id` varchar(36) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'UUID session identifier',
  `user_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'User ID',
  `world_id` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'World ID',
  `session_type` tinyint NOT NULL DEFAULT '1' COMMENT '会话类型: 1=剧本智能体, 2=营销智能体',
  `auth_token` varchar(500) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Authentication token',
  `model` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'deepseek-v4-flash' COMMENT 'AI model name',
  `model_id` int DEFAULT NULL COMMENT 'Model ID from vendor',
  `text_to_image_model_id` int DEFAULT NULL COMMENT 'Text-to-image model task ID',
  `conversation_history` longtext COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Serialized conversation history (JSON array)',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Session creation time',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update time',
  `expires_at` datetime DEFAULT NULL COMMENT 'Session expiration time (NULL = never expires)',
  `total_input_tokens` int NOT NULL DEFAULT '0' COMMENT 'Total input tokens used',
  `total_output_tokens` int NOT NULL DEFAULT '0' COMMENT 'Total output tokens used',
  `total_cache_creation_tokens` int NOT NULL DEFAULT '0' COMMENT 'Total cache creation tokens',
  `total_cache_read_tokens` int NOT NULL DEFAULT '0' COMMENT 'Total cache read tokens',
  `is_active` tinyint(1) NOT NULL DEFAULT '1' COMMENT 'Whether session is active (1=active, 0=inactive)',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_session_id` (`session_id`),
  KEY `idx_user_world_type` (`user_id`,`world_id`,`session_type`),
  KEY `idx_expires_at` (`expires_at`),
  KEY `idx_updated_at` (`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Chat sessions table'
"""
