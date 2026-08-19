# 智能体对话消息持久化与上下文构建设计

## 背景

当前智能体会话历史主要存储在 `chat_sessions.conversation_history` 这个 LONGTEXT JSON 数组中。PM Agent 执行任务时，消息先进入进程内存中的 `conversation_history`，任务完成后再由 `save_session()` 整体覆盖写入数据库。

这会导致几个问题：

- 任务执行中切换对话栏时，数据库中的历史可能还没有更新，前端只能看到旧历史或系统提示词。
- `conversation_history` 是整段覆盖写入，容易和前端补写、任务完成保存、压缩保存发生冲突。
- `agent_task_messages` 只负责 SSE 流式事件，不是完整会话历史。
- `agent_verifications` 只负责 ask_user 的等待与提交状态，也不是完整会话历史。
- 压缩历史时会改写内存历史，再整体覆盖数据库，原始历史不可追溯。

新设计将 `chat_messages` 作为唯一真实对话历史来源。一条消息对应一条数据库记录，任务执行中实时落库；`chat_sessions` 只保留会话元数据。

## 目标

- 用户消息、系统提示词、assistant 回复、工具调用、工具结果、verification 问题和答案都逐条落库。
- 前端切换会话时直接从 `chat_messages` 恢复完整历史，不依赖任务完成。
- 支持 DeepSeek `reasoning_content`、Gemini `thought_signature`、OpenAI `tool_calls` 等不同供应商格式。
- 支持上下文压缩，并且压缩后保留原始消息用于审计和排查。
- 支持摘要再次压缩，避免长会话持续增长后再次超出上下文。
- 新系统上线后不迁移旧 `chat_sessions.conversation_history`，旧历史允许丢失。
- 异步 Web 接口不得直接调用同步 DB 函数，避免阻塞 FastAPI 事件循环。

## 非目标

- 不迁移旧会话历史。
- 不在第一期重构整个数据库访问层为 async driver。
- 不改变现有 `agent_tasks`、`agent_task_messages`、`agent_verifications` 的核心职责。
- 不要求前端立即展示所有内部消息，例如工具定义、压缩元数据等。

## idempotency_key 生成规则

每条消息的 `idempotency_key` 必须全局唯一且稳定可重现（同一逻辑消息多次写入产生相同 key）。规则如下：

| 消息场景 | idempotency_key 格式 | 示例 |
|----------|----------------------|------|
| PM system prompt | `session:{session_id}:system:{prompt_hash[:16]}` | `session:abc123:system:a1b2c3d4e5f6g7h8` |
| 工具定义 | `session:{session_id}:tool_definitions` | `session:abc123:tool_definitions` |
| 用户消息（任务创建时） | `task:{task_id}:user:initial` | `task:t001:user:initial` |
| Agent 追加的用户消息 | `task:{task_id}:user:{content_hash[:16]}` | `task:t001:user:f1e2d3c4b5a69788` |
| verification 请求 | `verification:{verification_id}:request` | `verification:v001:request` |
| verification 答案 | `verification:{verification_id}:answer:{content_hash[:16]}` | `verification:v001:answer:9a8b7c6d5e4f3g2h` |
| assistant tool_call | `task:{task_id}:assistant:toolcall:{tool_call_ids_hash[:16]}` | `task:t001:assistant:toolcall:1a2b3c4d5e6f7g8h` |
| assistant 普通回复 | `task:{task_id}:assistant:{content_hash[:16]}:{timestamp_minute}` | `task:t001:assistant:h8g7f6e5:202606121050` |
| tool result | `task:{task_id}:tool:{tool_call_id}:result` | `task:t001:tool:call_abc123:result` |
| expert 内部消息 | `expert:{agent_id}:{task_id}:{local_index}` | `expert:img_under:t001:5` |

其中 `content_hash = sha256(json.dumps(content, ensure_ascii=False, sort_keys=True))`，`timestamp_minute = datetime.now().strftime('%Y%m%d%H%M')`。

**关键约束：**
- 同一逻辑消息从不同路径写入（如 verification 答案从 API 和 Agent 内存各写一次）必须生成相同 key。
- `local_index` 为 ExpertAgent 在当前任务中调用 `add_to_history` 的递增序号，避免 expert 内部消息 key 冲突。

## 核心原则

- `chat_messages` 是唯一真实历史来源。
- `provider_payload` 保存供应商原始消息结构，用于恢复 active 上下文。
- `LLMContextBuilder` 是从数据库消息到模型 API messages 的唯一转换入口。
- `context_state` 决定消息是否进入 LLM 上下文。
- 压缩不删除原始消息，只改变上下文视图。
- 工具调用消息组不能被拆开。

## 数据表设计

### chat_messages

```sql
CREATE TABLE `chat_messages` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT 'Primary key, global message order',
  `message_id` VARCHAR(64) NOT NULL COMMENT 'UUID message identifier',
  `session_id` VARCHAR(36) NOT NULL COMMENT 'Associated chat session ID',
  `task_id` VARCHAR(64) DEFAULT NULL COMMENT 'Associated agent task ID',
  `agent_id` VARCHAR(64) DEFAULT NULL COMMENT 'Agent identifier',
  `agent_scope` VARCHAR(16) NOT NULL DEFAULT 'pm' COMMENT 'pm/expert',

  `role` VARCHAR(32) NOT NULL COMMENT 'system/user/assistant/tool/summary/verification',
  `message_type` VARCHAR(32) NOT NULL COMMENT 'normal/tool_call/tool_result/verification_request/verification_answer/system_prompt/tool_definitions/context_summary',
  `content` LONGTEXT NOT NULL COMMENT 'Normalized content JSON for UI/system logic',

  `provider` VARCHAR(32) DEFAULT NULL COMMENT 'openai/gemini/deepseek/anthropic/litellm/etc',
  `api_format` VARCHAR(32) DEFAULT NULL COMMENT 'openai_chat/gemini_chat/anthropic_messages/etc',
  `provider_payload` LONGTEXT DEFAULT NULL COMMENT 'Original provider message JSON for active context reconstruction',
  `provider_meta` LONGTEXT DEFAULT NULL COMMENT 'Provider metadata JSON, tokens/reasoning_content/thought_signature/finish_reason/etc',

  `tool_call_id` VARCHAR(128) DEFAULT NULL COMMENT 'Tool call ID if this message belongs to a tool call group',
  `tool_name` VARCHAR(128) DEFAULT NULL COMMENT 'Tool name for tool call/result messages',
  `verification_id` VARCHAR(64) DEFAULT NULL COMMENT 'Verification ID for ask_user messages',

  `visibility` VARCHAR(16) NOT NULL DEFAULT 'both' COMMENT 'ui/llm/both/internal',
  `context_state` VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'active/summarized/excluded/deleted',
  `generated_summary_id` VARCHAR(64) DEFAULT NULL COMMENT 'Only for summary messages: the summary_id this message represents',
  `covered_by_summary_id` VARCHAR(64) DEFAULT NULL COMMENT 'For summarized messages: which summary covers this message',

  `idempotency_key` VARCHAR(128) NOT NULL COMMENT 'Deduplication key',
  `source` VARCHAR(32) NOT NULL COMMENT 'agent/frontend/verification/system/compression',

  `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_message_id` (`message_id`),
  UNIQUE KEY `uk_idempotency_key` (`idempotency_key`),
  KEY `idx_session_id_id` (`session_id`, `id`),
  KEY `idx_session_scope_id` (`session_id`, `agent_scope`, `id`),
  KEY `idx_session_context` (`session_id`, `context_state`, `id`),
  KEY `idx_task_id` (`task_id`),
  KEY `idx_verification_id` (`verification_id`),
  KEY `idx_generated_summary_id` (`generated_summary_id`),
  KEY `idx_covered_by_summary_id` (`covered_by_summary_id`),
  KEY `idx_create_at` (`create_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Agent chat messages, one row per message';
```

`system_prompt` 和 `tool_definitions` 是基础上下文消息，清空/替换聊天历史时不能软删除它们。若历史操作曾误将它们标记为 `deleted`，后续基础上下文补写必须基于稳定 `idempotency_key` 将其恢复为 `active`，否则 `LLMContextBuilder` 会构建出缺少系统提示词或工具定义的上下文。

`LLMContextBuilder` 是发送给模型前的最终协议防线：对于 OpenAI/DeepSeek 兼容格式，`assistant(tool_calls)` 后必须立即跟随每个 `tool_call_id` 对应的 `tool` 消息。数据库记录的是真实事件顺序，`verification_answer` 可能因为前端提交路径先于 Agent 写入 `tool_result`，从而出现在二者之间；构建 LLM 上下文时必须把完整 tool group 重排为 `assistant(tool_calls) -> tool_result... -> 其他消息`，并排除不完整或孤立的 tool 消息。

### chat_history_summaries

```sql
CREATE TABLE `chat_history_summaries` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `summary_id` VARCHAR(64) NOT NULL COMMENT 'UUID summary identifier',
  `session_id` VARCHAR(36) NOT NULL COMMENT 'Associated chat session ID',

  `from_message_id` BIGINT DEFAULT NULL COMMENT 'First normal message covered by this summary',
  `to_message_id` BIGINT DEFAULT NULL COMMENT 'Last normal message covered by this summary',
  `summary_message_id` BIGINT NOT NULL COMMENT 'chat_messages.id of the generated summary message',

  `summary_level` INT NOT NULL DEFAULT 1 COMMENT '1 for raw-message summary, 2+ for summary-of-summary',
  `parent_summary_ids` JSON DEFAULT NULL COMMENT 'Parent summaries absorbed by this summary',

  `summary_text` LONGTEXT NOT NULL COMMENT 'Summary text',
  `raw_message_count` INT NOT NULL DEFAULT 0 COMMENT 'Number of raw messages covered',

  `model_id` INT DEFAULT NULL COMMENT 'Model used to create summary',
  `vendor_id` INT DEFAULT NULL COMMENT 'Vendor used to create summary',

  `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_summary_id` (`summary_id`),
  KEY `idx_session_id` (`session_id`),
  KEY `idx_summary_message_id` (`summary_message_id`),
  KEY `idx_range` (`from_message_id`, `to_message_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Chat history compression summaries';
```

## 字段语义

### role

- `system`: 系统提示词。
- `user`: 用户输入，包括 verification 答案。
- `assistant`: 模型回复或工具调用请求。
- `tool`: 工具执行结果。
- `summary`: 历史摘要消息。
- `verification`: 仅供 UI 展示的 ask_user 问题。

### message_type

- `normal`: 普通 user/assistant 消息。
- `tool_call`: assistant 发起工具调用。
- `tool_result`: tool 返回结果。
- `verification_request`: ask_user 问题和选项。
- `verification_answer`: 用户对 ask_user 的回答。
- `system_prompt`: PM Agent 或专家 Agent 系统提示词。
- `tool_definitions`: 当前可用工具定义。
- `context_summary`: 历史压缩摘要。

### visibility

- `ui`: 只给前端展示。
- `llm`: 只进入模型上下文。
- `both`: 前端展示，也进入模型上下文。
- `internal`: 内部调试或复现信息，例如工具定义。

### context_state

- `active`: 可进入 LLM 上下文。
- `summarized`: 已被摘要覆盖，不再直接进入 LLM 上下文。
- `excluded`: 主动排除，例如错误写入、无效消息。
- `deleted`: 软删除。

## 写入流程

### 创建会话

1. `chat_sessions` 创建会话元数据。
2. PM Agent 初始化系统提示词。
3. 将系统提示词写入 `chat_messages`：

```json
{
  "role": "system",
  "message_type": "system_prompt",
  "content": {"text": "PM Agent system prompt..."},
  "visibility": "llm",
  "context_state": "active",
  "source": "system"
}
```

4. 将当前工具定义写入 `chat_messages`：

```json
{
  "role": "system",
  "message_type": "tool_definitions",
  "content": {"tools": []},
  "provider_payload": {"tools": []},
  "visibility": "internal",
  "context_state": "active",
  "source": "system"
}
```

### 创建任务

1. `POST /api/session/{session_id}/task` 创建 `agent_tasks`。
2. 将最终进入 PM Agent 的用户消息写入 `chat_messages`。
3. 如果包含图片、视频、音频、用户偏好，应写入归一化后的 `content`，并保留原始 URL。
4. 后台线程启动 PM Agent。

示例：

```json
{
  "role": "user",
  "message_type": "normal",
  "content": {
    "text": "分析这张图片",
    "image_urls": ["https://example.com/a.png"],
    "image_preferences": {"ratio": "16:9"}
  },
  "provider_payload": {
    "role": "user",
    "content": "分析这张图片\n\n[图片1] URL: https://example.com/a.png"
  },
  "visibility": "both",
  "context_state": "active",
  "source": "agent"
}
```

### Agent 追加历史

新增 `ConversationRecorder`，由 Agent 调用：

```python
class ConversationRecorder:
    def append_message(
        self,
        session_id: str,
        role: str,
        content: Any,
        message_type: str = "normal",
        task_id: str | None = None,
        agent_id: str | None = None,
        agent_scope: str = "pm",
        provider: str | None = None,
        api_format: str | None = None,
        provider_payload: dict | None = None,
        provider_meta: dict | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        verification_id: str | None = None,
        visibility: str = "both",
        source: str = "agent",
    ) -> ChatMessageEntity:
        ...
```

`BaseAgent.add_to_history()` 继续维护内存列表，但每次追加也通过 `ConversationRecorder` 落库。

### PM Agent 与 ExpertAgent 的写入边界

`PMAgent` 和 `MarketingPMAgent` 的消息是会话主线历史。它们写入 `chat_messages` 后，会被前端历史接口读取，也会被 `LLMContextBuilder` 用于恢复后续 PM 上下文。

`ExpertAgent` 也继承 `BaseAgent`，并且有独立的 system prompt 和 `conversation_history`。ExpertAgent 的消息也需要写入 `chat_messages`，但用途不同：

- 需要写入，用于审计、排查、追踪专家执行过程、统计工具调用、未来生成专家摘要。
- 默认不从 DB 读回 ExpertAgent 的完整历史来恢复专家实例。
- ExpertAgent 面向用户的普通 `assistant` 输出需要进入前端历史；system、tool_call、tool_result、普通 user 任务注入等内部过程默认不进入前端历史。
- PM 传给 ExpertAgent 的 `conversation_history` 只是专家执行上下文，写库时必须显式 `visibility = 'internal'`，不能当作 ExpertAgent 自己生成的输出展示。
- 默认不把 ExpertAgent 的完整内部历史直接放入 PM Agent 后续 LLM 上下文。
- PM Agent 后续上下文仍以 `call_agent` 的 tool_result 和 PM 自己追加的专家输出摘要为准。

因此 `chat_messages.agent_scope` 用来区分消息作用域：

- `agent_scope = 'pm'`：会话主线消息，可被前端和 PM 上下文读取。
- `agent_scope = 'expert'`：专家消息。普通 `assistant` 输出使用 `visibility = 'both'` 供前端展示；verification 问题使用 `ui`，verification 答案使用 `both`；system、tool_call、tool_result、普通 user 任务注入等内部消息使用 `internal` 或 `llm`，不进入普通聊天流。

ExpertAgent 写入示例：

```json
{
  "role": "assistant",
  "message_type": "normal",
  "content": {"text": "专家分析结果..."},
  "agent_id": "expert_image_understanding_xxx",
  "agent_scope": "expert",
  "visibility": "both",
  "context_state": "active",
  "source": "agent"
}
```

PM Agent 调用专家后，仍然需要在 PM 主线写入 tool_result：

```json
{
  "role": "tool",
  "message_type": "tool_result",
  "content": {
    "tool_name": "call_agent",
    "expert_agent_id": "expert_image_understanding_xxx",
    "result": "专家返回给 PM 的结果..."
  },
  "agent_scope": "pm",
  "visibility": "both",
  "context_state": "active",
  "source": "agent"
}
```

读取策略：

- `/session/{session_id}/history` 默认返回所有 `agent_scope` 中 `visibility in ('ui', 'both')` 的消息，因此 PM 主线消息和 ExpertAgent 面向用户的输出都能恢复显示。
- `LLMContextBuilder` 默认只读取 `agent_scope = 'pm'`。
- 调试接口可以按 `agent_id` 查询 ExpertAgent 内部历史。
- 压缩 PM 主线历史时只处理 `agent_scope = 'pm'`。
- ExpertAgent 内部历史可以后续独立压缩，或者仅作为审计数据保留。

### ask_user / verification

创建 verification 时立即写入问题：

```json
{
  "role": "verification",
  "message_type": "verification_request",
  "content": {
    "title": "PM Agent 向您提问",
    "description": "您希望对图片进行什么类型的分析？",
    "options": ["分析/理解这张图片", "生成类似图片"]
  },
  "verification_id": "ver_001",
  "visibility": "ui",
  "context_state": "active",
  "source": "verification"
}
```

用户提交答案时立即写入：

```json
{
  "role": "user",
  "message_type": "verification_answer",
  "content": {"text": "分析/理解这张图片"},
  "verification_id": "ver_001",
  "visibility": "both",
  "context_state": "active",
  "source": "verification"
}
```

PM Agent 后续再次把用户答案加入内存历史时，用 `verification_id + role + content_hash` 作为幂等键避免重复写入。

## LLMContextBuilder 设计

`LLMContextBuilder` 是 PM 主线会话恢复和后续 PM 调用的唯一上下文构造入口。

- PM Agent 的会话恢复和 `_build_messages_for_api()` 必须通过 `LLMContextBuilder` 从 `chat_messages` 构建。
- ExpertAgent 当前任务内可以继续用自身内存 `conversation_history`，但必须双写审计到 `chat_messages`（`agent_scope = 'expert'`），不默认从 DB 恢复专家实例。

### 接口

```python
from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class LLMContext:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]               # tool_definitions，作为 API 的 tools 参数
    tool_definition_message_ids: list[int]     # chat_messages.id of tool_definitions
    source_message_ids: list[int]
    omitted_message_ids: list[int]
    summary_message_ids: list[int]
    token_estimate: int


class LLMContextBuilder:
    def build(
        self,
        session_id: str,
        model: str,
        vendor_id: Optional[int] = None,
        model_id: Optional[int] = None,
        max_messages: Optional[int] = None,
        token_budget: Optional[int] = None,
    ) -> LLMContext:
        ...
```

### 构建步骤

1. 查询当前会话的 `chat_messages`。
2. 过滤 messages：
   - `visibility in ('llm', 'both')`（注意：`internal` 不进入 messages，工具定义等审计数据不应喂给 LLM）
   - `context_state = 'active'`
   - `agent_scope = 'pm'`
3. 单独读取 `message_type = 'tool_definitions'` 且 `visibility = 'internal'` 且 `context_state = 'active'` 的消息，提取 tools 列表放入 `LLMContext.tools`，不混入 `messages`。调用 API 时 `tools` 作为独立参数传递。
4. system prompt 放在最前。
5. active `context_summary` 放在 system prompt 后。
6. 普通 active 消息按 `id ASC` 排序。
7. 检查工具调用组是否完整。
8. 使用当前模型对应的 `LLMMessageAdapter` 转换格式。
9. 估算 token。
10. 如果超过预算，返回需要压缩的候选范围，或触发压缩流程后重新构建。

### 工具调用组完整性

以下消息组必须作为原子单位保留或压缩：

```text
assistant(tool_calls)
tool(tool_call_id=a)
tool(tool_call_id=b)
```

不能出现：

```text
assistant(tool_calls) 被压缩
tool_result 仍 active
```

也不能出现：

```text
assistant(tool_calls) active
tool_result 被压缩
```

如果检测到不完整工具组，`LLMContextBuilder` 应该：

1. 优先排除孤立 tool 消息。
2. 记录 warning 日志。
3. 不把不合法结构发给模型。

## LLMMessageAdapter 设计

### 注册表

```python
class LLMMessageAdapter:
    def to_api_message(self, message: ChatMessageEntity) -> dict | None:
        ...


class LLMMessageAdapterRegistry:
    def get_adapter(self, model: str, vendor_id: int | None, api_format: str | None) -> LLMMessageAdapter:
        ...
```

### 通用规则

- active 原始消息优先从 `provider_payload` 恢复。
- 如果 `provider_payload` 不存在，则从统一字段 `role/content/message_type` 构造。
- summarized 原始消息不进入上下文。
- context_summary 转成普通 system 上下文文本。
- verification_request 默认不进入 LLM，上下文只需要 verification_answer。

### OpenAI 兼容

assistant tool call：

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_001",
      "type": "function",
      "function": {
        "name": "ask_user",
        "arguments": "{\"question\":\"...\"}"
      }
    }
  ]
}
```

tool result：

```json
{
  "role": "tool",
  "tool_call_id": "call_001",
  "name": "ask_user",
  "content": "{\"success\":true,\"user_input\":\"分析/理解这张图片\"}"
}
```

### Gemini 兼容

active assistant tool call 如果包含 `thought_signature`，必须恢复：

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [],
  "thought_signature": "signature"
}
```

如果这条消息已被压缩，则不再回传原始 tool_call 和 `thought_signature`，只回传摘要。

Gemini 原生 API 不把系统提示词放进 `contents`，而是使用顶层 `systemInstruction`。因此 `LLMContextBuilder` 可以继续输出多条 OpenAI 风格的 `role = system` 消息，例如 PM system prompt 和 `context_summary`；最终进入 Gemini 客户端时必须合并成一个 `systemInstruction.parts[0].text`，不能让后出现的 system 消息覆盖前面的 system prompt。日志排查时也应检查顶层 `systemInstruction`，不能只看 `contents`。

### DeepSeek 兼容

active assistant 普通消息：

```json
{
  "role": "assistant",
  "content": "最终回答",
  "reasoning_content": "..."
}
```

如果当前 DeepSeek 客户端要求历史 assistant 消息带空 `reasoning_content`，adapter 可以补：

```json
{
  "role": "assistant",
  "content": "最终回答",
  "reasoning_content": ""
}
```

已压缩的 DeepSeek 原始消息不进入上下文。摘要消息不继承旧 `reasoning_content`。

## 压缩设计

压缩改变上下文视图，不删除原始数据。

### 第一次压缩

压缩前：

```text
id=1 system active
id=2..80 normal active
id=81..100 recent active
```

压缩后：

```text
id=1 system active
id=2..80 normal summarized covered_by_summary_id=sum_001
id=81..100 recent active
id=101 context_summary active generated_summary_id=sum_001
```

`chat_history_summaries`：

```json
{
  "summary_id": "sum_001",
  "session_id": "session_001",
  "from_message_id": 2,
  "to_message_id": 80,
  "summary_message_id": 101,
  "summary_level": 1,
  "parent_summary_ids": null,
  "summary_text": "用户希望制作科技风、高级感营销图...",
  "raw_message_count": 79
}
```

LLM 上下文：

```text
system id=1
summary id=101
recent id=81..100
```

### 摘要再次压缩

当已有摘要和后续 active 普通消息仍然过长时，可以把摘要也作为压缩输入。

压缩前：

```text
id=101 context_summary active summary_id=sum_001
id=81..160 normal active
id=161..200 recent active
```

压缩后：

```text
id=101 context_summary summarized covered_by_summary_id=sum_002
id=81..160 normal summarized covered_by_summary_id=sum_002
id=201 context_summary active generated_summary_id=sum_002
id=161..200 recent active
```

`chat_history_summaries`：

```json
{
  "summary_id": "sum_002",
  "session_id": "session_001",
  "from_message_id": 81,
  "to_message_id": 160,
  "summary_message_id": 201,
  "summary_level": 2,
  "parent_summary_ids": ["sum_001"],
  "summary_text": "用户已确认科技风和高级感方向，并完成图片理解...",
  "raw_message_count": 80
}
```

### 压缩候选优先级

1. 压缩旧的 active 普通消息。
2. 如果普通消息不够压缩，压缩多个 active summary。
3. 如果只剩 1 条 active summary 和最近 N 条消息，停止自动压缩。
4. 停止后可以缩小最近消息窗口，或返回上下文过大错误。

手动压缩接口 `/session/{session_id}/compress` 也必须以 `chat_messages` 中的 active PM 上下文消息数量作为 `before_count/after_count`，不能再用 PM Agent 内存里的 `conversation_history` 计数。接口从最近的 `agent_tasks` 记录恢复 `AgentTask` 时，应使用真实字段 `user_message/auth_token/vendor_id/model_id/enable_thinking/thinking_effort/language`，不得传入不存在的 `prompt` 字段。

### 禁止压缩的内容

- system prompt。
- 当前工具定义。
- 当前未完成的 tool_call/tool_result 组。
- 当前等待用户回答的 verification。
- 最近 N 条消息。
- 被标记为 `excluded` 或 `deleted` 的消息。

## 读取历史 API

`GET /api/session/{session_id}/history` 改为查询 `chat_messages`。

默认只返回：

```text
visibility in ('ui', 'both')
context_state != 'deleted'
```

前端展示时：

- `normal` 按普通 user/assistant 消息展示。
- `verification_request` 还原为按钮/输入框。
- `summarized` 原始消息默认展示（灰色或带标记），保持用户可见的完整聊天历史。
- `message_type = 'context_summary'` 默认不展示在聊天流中，可在消息列表顶部以折叠”历史摘要”卡片形式呈现。
- 这样避免前端同时显示”原始消息 + 摘要消息”导致重复。

## save_session 调整

`SessionStorage.save_session()` 不再更新 `chat_sessions.conversation_history`。

它只更新：

- `model`
- `model_id`
- `text_to_image_model_id`
- `expires_at`
- token 统计
- `updated_at`

`chat_sessions.conversation_history` 字段保留但废弃，新逻辑不读不写。

## 会话过期与顺延策略

会话是否被清理取决于 `chat_sessions.expires_at`：`task/session_cleanup.py` 定时任务（每 6 小时）硬删除 `expires_at <= now AND is_active = 1` 的会话行；前端随后因查不到活跃会话而新建空会话（旧 `chat_messages` 行成为孤儿数据，暂未清理）。

过期时长常量见 `config/constant.py` 的 `SessionHistoryConstants`：

- 剧本智能体（`session_type=1`）：`SESSION_EXPIRE_HOURS_SCRIPT = 72`（3 天）
- 营销智能体（`session_type=2`）：`SESSION_EXPIRE_HOURS_MARKETING = 336`（14 天）

`expires_at` 锚定为"最近一次消息活动时间"，以下入口都会顺延为 `now + 过期时长`（API 层统一经 `_extend_session_expiry()`，以 `asyncio.to_thread` 包装，失败仅记日志不影响主流程）：

- 创建会话（`/session/create`）
- 发送消息创建任务（`/session/{id}/task`，用户消息写入时即顺延，覆盖任务失败不顺延的缺口）
- 追加消息（`/session/{id}/message`）
- 提交验证回答（`/verification/{id}`）
- 任务成功完成回调（`on_task_complete` → `save_session()`）
- 切换会话模型（`/session/{id}/model`）

## 非阻塞要求

当前数据库层使用 `pymysql` 同步函数。落地时必须遵守：

- FastAPI async 路由中不能直接调用同步 DB 函数。
- async 路由中使用 `await asyncio.to_thread(Model.method, ...)` 包装同步 DB 调用。
- Agent 后台线程中可以直接同步写 DB，因为不占用事件循环。
- 后续如果重构为 `aiomysql` 或 async SQLAlchemy，`ConversationRecorder` 和 `LLMContextBuilder` 的接口保持不变。

## 与现有表关系

### chat_sessions

保留会话元数据。废弃 `conversation_history` 作为历史来源。

### agent_tasks

继续表示任务生命周期和状态。

### agent_task_messages

继续作为 SSE 事件表。它不是历史真源。

### agent_verifications

继续作为 ask_user 等待状态表。创建和提交 verification 时，同步向 `chat_messages` 写入可展示、可恢复的会话消息。

## 上线策略

- 不迁移旧 `chat_sessions.conversation_history`。
- 新版本上线后，新消息全部写入 `chat_messages`。
- `/session/{session_id}/history` 只读 `chat_messages`。
- 旧会话如果没有 `chat_messages`，返回空历史。
- 可以保留旧字段和旧代码路径一段时间，但不得再作为真实历史来源。

## 测试要求

### 单元测试

- `ChatMessagesModel.create()` 幂等插入。
- `ChatMessagesModel.list_for_session()` 顺序正确。
- `LLMContextBuilder` 只选择 active 消息。
- `LLMContextBuilder` 默认只选择 `agent_scope = 'pm'` 消息。
- `LLMContextBuilder` 不拆 tool_call/tool_result 组。
- OpenAI adapter 恢复 `tool_calls/tool_call_id`。
- Gemini adapter 恢复 active `thought_signature`。
- DeepSeek adapter 恢复 active `reasoning_content` 或补空字段。
- summarized 原始消息不会进入 LLM 上下文。
- context_summary 会进入 LLM 上下文。
- 二级摘要能正确标记 parent summary。

### 集成测试

- 创建会话后立即能从 `chat_messages` 看到 system prompt。
- 创建任务后，用户消息立即落库，任务未完成时切换会话也能看到。
- ask_user 问题出现时，`verification_request` 立即落库。
- 用户提交 verification 后，`verification_answer` 立即落库。
- 任务完成后不会整体覆盖历史。
- 压缩后 UI 仍能查询原始消息，LLM 上下文只使用摘要和最近消息。
- ExpertAgent 消息会写入 `chat_messages`，但不会出现在普通历史接口和 PM 上下文中。

### 回归测试

- script_writer.html 历史加载正常。
- marketing_agent.html 历史加载正常。
- 多 worker 场景下 SSE 和历史查询一致。
- 异步 API 没有直接阻塞事件循环的同步 DB 调用。

## 风险与约束

- 第一阶段仍使用同步 DB driver，必须严格用 `asyncio.to_thread` 包装 async 路由中的 DB 调用。
- `provider_payload` 可能较大，需要控制写入内容，避免保存不必要的大对象。
- 工具调用组完整性非常重要，否则 OpenAI/Gemini/DeepSeek 都可能报上下文格式错误。
- 压缩摘要质量会影响后续模型表现，应保留原文并记录 summary 覆盖范围，便于排查。
- `idempotency_key` 设计要稳定，否则 verification 答案和 Agent 内存回放可能重复写入。

## 推荐实施顺序

1. 新增 Alembic 迁移和 `model/chat_messages.py`、`model/chat_history_summaries.py`。
2. 新增 `ConversationRecorder`，先提供显式调用，不马上替换所有历史逻辑。
3. 改会话创建和任务创建，将 PM system prompt、工具定义、用户消息写入 `chat_messages`。
4. 改 ask_user / verification 写入链路。
5. 将 ExpertAgent 的 `add_to_history()` 写入 `chat_messages`，使用 `agent_scope = 'expert'`；普通 assistant 输出 `visibility = 'both'`，内部过程使用 `internal/llm`。
6. 新增 `LLMContextBuilder` 和供应商 adapter。
7. 将 PM Agent 的 `_build_messages_for_api()` 切换到 `LLMContextBuilder`。
8. 改 `/session/{session_id}/history` 从 `chat_messages` 读取。
9. 调整 `save_session()`，停止覆盖 `conversation_history`。
10. 实现压缩和二次压缩。
11. 更新前端历史渲染和相关文档。
