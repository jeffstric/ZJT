"""
Chat Messages Model - Database operations for chat_messages table

每条消息对应一条数据库记录，替代 chat_sessions.conversation_history JSON 整体覆盖。
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

from .database import execute_query, execute_update, execute_insert, transaction, execute_insert_in_transaction, execute_update_in_transaction
import logging

logger = logging.getLogger(__name__)


class ChatMessageEntity:
    """Chat message database entity class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.message_id = kwargs.get('message_id')
        self.session_id = kwargs.get('session_id')
        self.task_id = kwargs.get('task_id')
        self.agent_id = kwargs.get('agent_id')
        self.agent_scope = kwargs.get('agent_scope', 'pm')

        self.role = kwargs.get('role')
        self.message_type = kwargs.get('message_type')

        # Deserialize content from JSON
        content_raw = kwargs.get('content')
        if isinstance(content_raw, str):
            try:
                self.content = json.loads(content_raw)
            except (json.JSONDecodeError, TypeError):
                self.content = content_raw
        else:
            self.content = content_raw

        self.provider = kwargs.get('provider')
        self.api_format = kwargs.get('api_format')

        # Deserialize provider_payload from JSON
        pp_raw = kwargs.get('provider_payload')
        if isinstance(pp_raw, str):
            try:
                self.provider_payload = json.loads(pp_raw)
            except (json.JSONDecodeError, TypeError):
                self.provider_payload = None
        else:
            self.provider_payload = pp_raw

        # Deserialize provider_meta from JSON
        pm_raw = kwargs.get('provider_meta')
        if isinstance(pm_raw, str):
            try:
                self.provider_meta = json.loads(pm_raw)
            except (json.JSONDecodeError, TypeError):
                self.provider_meta = None
        else:
            self.provider_meta = pm_raw

        self.tool_call_id = kwargs.get('tool_call_id')
        self.tool_name = kwargs.get('tool_name')
        self.verification_id = kwargs.get('verification_id')

        # visibility 控制消息对谁可见：'user'(仅用户) / 'llm'(仅LLM上下文) / 'both'(两者) / 'internal'(内部，如tool_definitions)
        self.visibility = kwargs.get('visibility', 'both')
        # context_state 控制消息是否参与 LLM 上下文：'active'(正常) / 'summarized'(已被摘要替代) / 'deleted'(软删除)
        self.context_state = kwargs.get('context_state', 'active')
        self.generated_summary_id = kwargs.get('generated_summary_id')
        self.covered_by_summary_id = kwargs.get('covered_by_summary_id')

        self.idempotency_key = kwargs.get('idempotency_key')
        self.source = kwargs.get('source')

        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'message_id': self.message_id,
            'session_id': self.session_id,
            'task_id': self.task_id,
            'agent_id': self.agent_id,
            'agent_scope': self.agent_scope,
            'role': self.role,
            'message_type': self.message_type,
            'content': self.content,
            'provider': self.provider,
            'api_format': self.api_format,
            'provider_payload': self.provider_payload,
            'provider_meta': self.provider_meta,
            'tool_call_id': self.tool_call_id,
            'tool_name': self.tool_name,
            'verification_id': self.verification_id,
            'visibility': self.visibility,
            'context_state': self.context_state,
            'generated_summary_id': self.generated_summary_id,
            'covered_by_summary_id': self.covered_by_summary_id,
            'idempotency_key': self.idempotency_key,
            'source': self.source,
            'create_at': self.create_at.isoformat() if isinstance(self.create_at, datetime) else self.create_at,
            'update_at': self.update_at.isoformat() if isinstance(self.update_at, datetime) else self.update_at,
        }

    def to_frontend_dict(self) -> Dict[str, Any]:
        """Convert to frontend-expected format {role, content, timestamp, message_type}"""
        result = {
            'role': self.role,
            'content': self.content,
            'timestamp': self.create_at.isoformat() if isinstance(self.create_at, datetime) else str(self.create_at),
            'message_type': self.message_type,
            'message_id': self.message_id,
        }

        # verification_request 还原为前端可用的结构
        if self.message_type == 'verification_request' and isinstance(self.content, dict):
            verification_status = self.content.get('status')
            result['role'] = 'verification'
            result['verification_status'] = verification_status
            result['content'] = {
                'verification_id': self.verification_id,
                'title': self.content.get('title', ''),
                'description': self.content.get('description', ''),
                'options': self.content.get('options', []),
                'status': verification_status,
            }

        return result


class ChatMessagesModel:
    """Static methods for chat_messages table operations"""

    @staticmethod
    def _row_to_entity(row: Dict[str, Any]) -> ChatMessageEntity:
        """Convert a database row dict to ChatMessageEntity"""
        return ChatMessageEntity(**row)

    @staticmethod
    def create(
        message_id: str,
        session_id: str,
        role: str,
        message_type: str,
        content: str,
        idempotency_key: str,
        source: str,
        agent_scope: str = 'pm',
        context_state: str = 'active',
        task_id: str = None,
        agent_id: str = None,
        provider: str = None,
        api_format: str = None,
        provider_payload: str = None,
        provider_meta: str = None,
        tool_call_id: str = None,
        tool_name: str = None,
        verification_id: str = None,
        visibility: str = 'both',
        generated_summary_id: str = None,
        covered_by_summary_id: str = None,
    ) -> Optional[ChatMessageEntity]:
        """
        Idempotent insert. Uses INSERT ... ON DUPLICATE KEY UPDATE on uk_idempotency_key.
        If idempotency_key already exists, returns the existing record.
        """
        sql = """
            INSERT INTO `chat_messages` (
                message_id, session_id, role, message_type, content,
                idempotency_key, source, agent_scope, context_state,
                task_id, agent_id, provider, api_format,
                provider_payload, provider_meta,
                tool_call_id, tool_name, verification_id,
                visibility, generated_summary_id, covered_by_summary_id
            ) VALUES (
                %(message_id)s, %(session_id)s, %(role)s, %(message_type)s, %(content)s,
                %(idempotency_key)s, %(source)s, %(agent_scope)s, %(context_state)s,
                %(task_id)s, %(agent_id)s, %(provider)s, %(api_format)s,
                %(provider_payload)s, %(provider_meta)s,
                %(tool_call_id)s, %(tool_name)s, %(verification_id)s,
                %(visibility)s, %(generated_summary_id)s, %(covered_by_summary_id)s
            )
            ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)
        """
        params = {
            'message_id': message_id,
            'session_id': session_id,
            'role': role,
            'message_type': message_type,
            'content': content,
            'idempotency_key': idempotency_key,
            'source': source,
            'agent_scope': agent_scope,
            'context_state': context_state,
            'task_id': task_id,
            'agent_id': agent_id,
            'provider': provider,
            'api_format': api_format,
            'provider_payload': provider_payload,
            'provider_meta': provider_meta,
            'tool_call_id': tool_call_id,
            'tool_name': tool_name,
            'verification_id': verification_id,
            'visibility': visibility,
            'generated_summary_id': generated_summary_id,
            'covered_by_summary_id': covered_by_summary_id,
        }

        last_id = execute_insert(sql, params)

        # If LAST_INSERT_ID matches the ON DUPLICATE KEY case, fetch existing record
        row = execute_query(
            "SELECT * FROM `chat_messages` WHERE id = %s",
            (last_id,),
            fetch_one=True
        )
        if row:
            return ChatMessagesModel._row_to_entity(row)
        return None

    @staticmethod
    def get_by_message_id(message_id: str) -> Optional[ChatMessageEntity]:
        """Get a message by its UUID message_id"""
        row = execute_query(
            "SELECT * FROM `chat_messages` WHERE message_id = %s",
            (message_id,),
            fetch_one=True
        )
        return ChatMessagesModel._row_to_entity(row) if row else None

    @staticmethod
    def list_for_session(
        session_id: str,
        *,
        agent_scope: str = None,
        visibility: List[str] = None,
        exclude_context_state: List[str] = None,
        exclude_message_types: List[str] = None,
        limit: int = None,
        offset: int = None,
    ) -> List[ChatMessageEntity]:
        """List messages for a session, ordered by id ASC"""
        conditions = ["session_id = %s"]
        params: list = [session_id]

        if agent_scope:
            conditions.append("agent_scope = %s")
            params.append(agent_scope)

        if visibility:
            placeholders = ", ".join(["%s"] * len(visibility))
            conditions.append(f"visibility IN ({placeholders})")
            params.extend(visibility)

        if exclude_context_state:
            placeholders = ", ".join(["%s"] * len(exclude_context_state))
            conditions.append(f"context_state NOT IN ({placeholders})")
            params.extend(exclude_context_state)

        if exclude_message_types:
            placeholders = ", ".join(["%s"] * len(exclude_message_types))
            conditions.append(f"message_type NOT IN ({placeholders})")
            params.extend(exclude_message_types)

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM `chat_messages` WHERE {where} ORDER BY id ASC"

        if limit:
            sql += " LIMIT %s"
            params.append(limit)
            if offset:
                sql += " OFFSET %s"
                params.append(offset)

        rows = execute_query(sql, tuple(params), fetch_all=True)
        return [ChatMessagesModel._row_to_entity(r) for r in (rows or [])]

    @staticmethod
    def list_active_for_context(session_id: str, agent_scope: str = 'pm') -> List[ChatMessageEntity]:
        """Query messages for LLM context: visibility IN ('llm','both') AND context_state = 'active' AND agent_scope = ?"""
        sql = """
            SELECT * FROM `chat_messages`
            WHERE session_id = %s AND agent_scope = %s
              AND visibility IN ('llm', 'both')
              AND context_state = 'active'
            ORDER BY id ASC
        """
        rows = execute_query(sql, (session_id, agent_scope), fetch_all=True)
        return [ChatMessagesModel._row_to_entity(r) for r in (rows or [])]

    @staticmethod
    def get_tool_definitions(session_id: str, agent_scope: str = 'pm') -> Optional[ChatMessageEntity]:
        """Read active tool_definitions for a session (visibility='internal', message_type='tool_definitions')"""
        sql = """
            SELECT * FROM `chat_messages`
            WHERE session_id = %s AND agent_scope = %s
              AND message_type = 'tool_definitions'
              AND context_state = 'active'
            ORDER BY id DESC LIMIT 1
        """
        row = execute_query(sql, (session_id, agent_scope), fetch_one=True)
        return ChatMessagesModel._row_to_entity(row) if row else None

    @staticmethod
    def update_context_state(
        message_ids: List[int],
        context_state: str,
        covered_by_summary_id: str = None,
    ) -> int:
        """Batch update context_state and optionally covered_by_summary_id"""
        if not message_ids:
            return 0

        if covered_by_summary_id:
            sql = """
                UPDATE `chat_messages`
                SET context_state = %s, covered_by_summary_id = %s
                WHERE id IN (%s)
            """ % ("%s", "%s", ", ".join(["%s"] * len(message_ids)))
            params = [context_state, covered_by_summary_id] + message_ids
        else:
            sql = """
                UPDATE `chat_messages`
                SET context_state = %s
                WHERE id IN (%s)
            """ % ("%s", ", ".join(["%s"] * len(message_ids)))
            params = [context_state] + message_ids

        return execute_update(sql, tuple(params))

    @staticmethod
    def soft_delete(message_id: str) -> int:
        """Set context_state = 'deleted'"""
        return execute_update(
            "UPDATE `chat_messages` SET context_state = 'deleted' WHERE message_id = %s",
            (message_id,)
        )

    @staticmethod
    def update_content(message_id: str, content: str, message_type: str = None, session_id: str = None) -> int:
        """更新指定消息的内容和类型（用于 pending → 结果替换）

        Args:
            message_id: 消息唯一标识
            content: 新内容
            message_type: 新消息类型（可选）
            session_id: 会话 ID，传入时会校验消息归属，防止跨会话误更新
        """
        session_condition = " AND session_id = %s" if session_id else ""

        if message_type:
            sql = f"""
                UPDATE `chat_messages`
                SET content = %s, message_type = %s
                WHERE message_id = %s{session_condition}
            """
            params = [content, message_type, message_id]
        else:
            sql = f"""
                UPDATE `chat_messages`
                SET content = %s
                WHERE message_id = %s{session_condition}
            """
            params = [content, message_id]

        if session_id:
            params.append(session_id)

        return execute_update(sql, tuple(params))

    @staticmethod
    def replace_pending_task(session_id: str, event_type: str, project_ids: list, new_content: str) -> int:
        """按 session_id + event_type + project_ids 查找 pending_task 消息并替换内容和类型。

        用于轮询完成时将后端 pending 行直接更新为结果，不依赖前端内存标记。
        返回受影响行数。
        """
        # 构建匹配的 content 前缀
        import json as _json
        target_content = f'__PENDING_TASK__:{event_type}:{_json.dumps(project_ids)}'

        sql = """
            UPDATE `chat_messages`
            SET content = %s, message_type = 'text'
            WHERE session_id = %s
              AND message_type = 'pending_task'
              AND context_state = 'active'
              AND content = %s
        """
        return execute_update(sql, (new_content, session_id, target_content))

    @staticmethod
    def count_for_session(session_id: str) -> int:
        """Count messages for a session"""
        row = execute_query(
            "SELECT COUNT(*) as cnt FROM `chat_messages` WHERE session_id = %s",
            (session_id,),
            fetch_one=True
        )
        return row['cnt'] if row else 0
