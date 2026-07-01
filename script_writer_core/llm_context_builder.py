"""
LLMContextBuilder - 从 chat_messages 数据库构建 LLM API 所需的 messages + tools

PM 主线会话恢复和后续 PM 调用的唯一上下文构造入口。
ExpertAgent 允许继续用内存历史，不默认走此路径。
"""
from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict
import json
import logging

from model.chat_messages import ChatMessageEntity, ChatMessagesModel

logger = logging.getLogger(__name__)


@dataclass
class LLMContext:
    """LLM 调用所需的完整上下文"""
    messages: List[Dict[str, Any]]
    tools: List[Dict[str, Any]]                # tool_definitions，作为 API tools 参数
    tool_definition_message_ids: List[int]     # chat_messages.id of tool_definitions
    source_message_ids: List[int]
    omitted_message_ids: List[int]
    summary_message_ids: List[int]
    token_estimate: int


class LLMContextBuilder:
    """从 chat_messages 表构建 LLM 上下文"""

    def build(
        self,
        session_id: str,
        model: str,
        vendor_id: Optional[int] = None,
        model_id: Optional[int] = None,
        max_messages: Optional[int] = None,
        token_budget: Optional[int] = None,
    ) -> LLMContext:
        """
        构建上下文。返回 LLMContext 包含 messages + tools。
        """
        from script_writer_core.llm_message_adapter import LLMMessageAdapterRegistry

        # 1. 查询 active messages（visibility in ('llm', 'both')）
        active_messages = ChatMessagesModel.list_active_for_context(session_id, agent_scope='pm')

        # 2. 单独读取 tool_definitions
        tool_def_entity = ChatMessagesModel.get_tool_definitions(session_id)
        tools = []
        tool_def_ids = []
        if tool_def_entity:
            tool_def_ids.append(tool_def_entity.id)
            if isinstance(tool_def_entity.content, dict) and 'tools' in tool_def_entity.content:
                tools = tool_def_entity.content['tools']
            elif isinstance(tool_def_entity.provider_payload, dict) and 'tools' in tool_def_entity.provider_payload:
                tools = tool_def_entity.provider_payload['tools']

        # 3. 分类消息：system prompt、context_summary、普通消息
        system_messages = []
        summary_messages = []
        normal_messages = []

        for msg in active_messages:
            if msg.message_type == 'system_prompt':
                system_messages.append(msg)
            elif msg.message_type == 'context_summary':
                summary_messages.append(msg)
            elif msg.message_type == 'tool_definitions':
                continue  # 已单独处理
            else:
                normal_messages.append(msg)

        # 4. 检查工具调用组完整性
        complete_messages, omitted_ids = self._check_tool_call_groups(normal_messages)

        # 5. 按顺序组装：system → summary → normal
        ordered = system_messages + summary_messages + complete_messages

        # 6. 获取 adapter 并转换
        adapter_registry = LLMMessageAdapterRegistry()
        adapter = adapter_registry.get_adapter(model, vendor_id)

        api_messages = []
        source_ids = []
        summary_ids = [m.id for m in summary_messages]

        for msg in ordered:
            api_msg = adapter.to_api_message(msg)
            if api_msg is not None:
                api_messages.append(api_msg)
                source_ids.append(msg.id)

        # 7. 估算 token
        token_estimate = self._estimate_tokens(api_messages)

        return LLMContext(
            messages=api_messages,
            tools=tools,
            tool_definition_message_ids=tool_def_ids,
            source_message_ids=source_ids,
            omitted_message_ids=omitted_ids,
            summary_message_ids=summary_ids,
            token_estimate=token_estimate,
        )

    def _check_tool_call_groups(
        self, messages: List[ChatMessageEntity]
    ) -> tuple:
        """
        检查工具调用组完整性。

        assistant(tool_calls) 后面必须跟完整的 tool(tool_call_id) 消息。
        不完整的组整组排除。
        """
        # 构建 id → message 的映射
        msg_by_id = {m.id: m for m in messages}

        # 找到所有 tool_call 消息
        normalized_messages = []
        omitted_ids = set()
        consumed_tool_result_ids = set()

        for idx, msg in enumerate(messages):
            if msg.id in consumed_tool_result_ids or msg.id in omitted_ids:
                continue

            if msg.message_type == 'tool_result':
                omitted_ids.add(msg.id)
                logger.warning(
                    f"LLMContextBuilder: Orphan tool_result id={msg.id}, tool_call_id={msg.tool_call_id}"
                )
                continue

            if msg.message_type != 'tool_call':
                normalized_messages.append(msg)
                continue

            call_ids = self._extract_tool_call_ids(msg)
            if not call_ids:
                normalized_messages.append(msg)
                continue

            group_results = []
            missing_call_ids = []
            for cid in call_ids:
                result_msg = next(
                    (
                        m for m in messages[idx + 1:]
                        if (
                            m.message_type == 'tool_result'
                            and m.tool_call_id == cid
                            and m.id not in consumed_tool_result_ids
                            and m.id not in omitted_ids
                        )
                    ),
                    None
                )
                if result_msg is None:
                    missing_call_ids.append(cid)
                else:
                    group_results.append(result_msg)

            if missing_call_ids:
                omitted_ids.add(msg.id)
                for result_msg in group_results:
                    omitted_ids.add(result_msg.id)
                logger.warning(
                    f"LLMContextBuilder: Incomplete tool call group for assistant message id={msg.id}, "
                    f"missing_call_ids={missing_call_ids}, call_ids={call_ids}"
                )
                continue

            # OpenAI/DeepSeek require assistant(tool_calls) to be followed
            # immediately by every corresponding tool result. DB write order can
            # contain verification_answer between them, so normalize here.
            normalized_messages.append(msg)
            for result_msg in group_results:
                normalized_messages.append(result_msg)
                consumed_tool_result_ids.add(result_msg.id)

        return normalized_messages, list(omitted_ids)

        # ⚠️ 以下代码为死代码（return 之后永远不会执行）
        # 是 _check_tool_call_groups 的旧实现，保留作为参考
        tool_call_msgs = []
        for msg in messages:
            if msg.message_type == 'tool_call':
                tool_call_msgs.append(msg)

        # 从每个 tool_call 消息的 provider_payload 中提取所有 tool_call_id
        complete_call_ids = set()
        incomplete_groups = []

        for tc_msg in tool_call_msgs:
            call_ids = self._extract_tool_call_ids(tc_msg)
            if not call_ids:
                # 无法提取 call_ids，保留消息
                complete_call_ids.add(tc_msg.id)
                continue

            # 检查每个 call_id 是否有对应的 tool_result
            all_found = True
            for cid in call_ids:
                found = any(
                    m.message_type == 'tool_result' and m.tool_call_id == cid
                    for m in messages
                )
                if not found:
                    all_found = False
                    break

            if all_found:
                complete_call_ids.add(tc_msg.id)
                for cid in call_ids:
                    # 标记对应的 tool_result 也是完整的
                    for m in messages:
                        if m.message_type == 'tool_result' and m.tool_call_id == cid:
                            complete_call_ids.add(m.id)
            else:
                incomplete_groups.append(tc_msg.id)
                logger.warning(
                    f"LLMContextBuilder: Incomplete tool call group for assistant message id={tc_msg.id}, "
                    f"call_ids={call_ids}"
                )

        # 找到孤立的 tool_result（没有对应的 tool_call）
        orphan_tool_results = []
        for m in messages:
            if m.message_type == 'tool_result' and m.id not in complete_call_ids:
                orphan_tool_results.append(m.id)
                logger.warning(
                    f"LLMContextBuilder: Orphan tool_result id={m.id}, tool_call_id={m.tool_call_id}"
                )

        # 分离完整和不完整的消息
        omitted_ids = set(incomplete_groups) | set(orphan_tool_results)
        complete = [m for m in messages if m.id not in omitted_ids]

        return complete, list(omitted_ids)

    def _extract_tool_call_ids(self, msg: ChatMessageEntity) -> List[str]:
        """从 assistant tool_call 消息中提取所有 tool_call ID"""
        ids = []

        # 优先从 provider_payload 提取
        payload = msg.provider_payload
        if isinstance(payload, dict) and 'tool_calls' in payload:
            for tc in payload['tool_calls']:
                if isinstance(tc, dict) and 'id' in tc:
                    ids.append(tc['id'])

        # 备选：从 content 提取
        if not ids and isinstance(msg.content, dict) and 'tool_calls' in msg.content:
            for tc in msg.content['tool_calls']:
                if isinstance(tc, dict) and 'id' in tc:
                    ids.append(tc['id'])

        return ids

    @staticmethod
    def _estimate_tokens(messages: List[Dict[str, Any]]) -> int:
        """简单估算 token 数量（约 3 字符 = 1 token）"""
        total_chars = 0
        for msg in messages:
            content = msg.get('content', '')
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total_chars += len(json.dumps(part, ensure_ascii=False))
                    elif isinstance(part, str):
                        total_chars += len(part)
            # tool_calls
            if 'tool_calls' in msg:
                total_chars += len(json.dumps(msg['tool_calls'], ensure_ascii=False))
            # reasoning_content
            if 'reasoning_content' in msg and msg['reasoning_content']:
                total_chars += len(msg['reasoning_content'])
        return total_chars // 3
