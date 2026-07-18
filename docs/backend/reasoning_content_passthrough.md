# Reasoning Content 回传机制

## 问题背景

支持思考模式的 LLM API（如 DeepSeek 推理模型）在响应中返回 `reasoning_content` 字段，**要求在后续请求中将其原样传回**。如果未回传，API 会返回 429 错误：

```
The `reasoning_content` in the thinking mode must be passed back to the API
```

## 修复方案

### 数据流

```
API 响应 → 提取 reasoning_content → 存入对话历史 → 构建 API 消息时回传
```

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `llm/base_llm_client.py` | `Message` 类增加 `reasoning_content` 字段；`_create_response()` 方法支持传入 |
| `llm/openai_base_client.py` | 从 API 响应中提取 `reasoning_content`，传递给 `_create_response()` |
| `llm/ollama_client.py` | 同上，同步提取并传递 |
| `script_writer_core/agents/pm_agent.py` | 存储 `reasoning_content` 到历史；`_build_messages_for_api()` 回传 |
| `script_writer_core/agents/expert_agent.py` | 存储 `reasoning_content` 到历史；`_format_messages_for_api()` 回传 |

### 历史存储格式

**无 reasoning_content 时**（普通模型）：
```python
{"role": "assistant", "content": "文本内容"}
```

**有 reasoning_content 时**（推理模型）：
```python
{"role": "assistant", "content": {"text": "文本内容", "reasoning_content": "推理过程"}}
```

**tool_calls + reasoning_content 时**：
```python
{"role": "assistant", "content": {"tool_calls": [...], "reasoning_content": "推理过程"}}
```

### API 消息构建

构建 API 请求消息时，如果 assistant 历史记录包含 `reasoning_content`，会将其作为顶级字段回传：

```python
{
    "role": "assistant",
    "content": "文本内容",
    "reasoning_content": "推理过程"  # 回传给 API
}
```

这与 `thought_signature`（Gemini 模型）的处理方式一致。

### 脚本解析入口

`/api/parse-script` 和故事板“从剧本生成”入口会接收 `enable_thinking`、`thinking_effort`，并透传到 `llm.script_parser.parse_script_to_shots()`。前端剧本节点在拆分模型支持思考模式时显示开关，DeepSeek 系列模型默认开启；用户手动关闭后会随工作流保存和重载恢复。
