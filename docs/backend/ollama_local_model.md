# Ollama 本地模型支持

本文档介绍如何配置和使用 Ollama 本地模型作为剧本智能体的 LLM 后端。

## 概述

Ollama 是一个本地运行大语言模型的工具，支持 Llama、Qwen、Mistral 等多种开源模型。本系统支持通过 Ollama 的 OpenAI 兼容接口调用本地模型。

## 前置要求

1. 安装 Ollama：https://ollama.ai
2. 下载支持 Tool Calling 的模型（如 `qwen2.5:7b`、`llama3.1:8b`）

```bash
# 下载模型示例
ollama pull qwen2.5:7b
ollama pull llama3.1:8b
```

## 配置步骤

### 1. 启用 Ollama

在 `config.yml` 中配置：

```yaml
llm:
  ollama:
    enabled: true
    base_url: "http://localhost:11434"
    # 模型参数配置
    temperature: 0.7
    top_p: 0.8
    top_k: 20
    min_p: 0.0
    presence_penalty: 1.5
    repetition_penalty: 1.0
    enable_thinking: false
```

或在管理后台的"快速配置"中启用和调整参数：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `llm.ollama.enabled` | 是否启用 | `false` |
| `llm.ollama.base_url` | 服务地址 | `http://localhost:11434` |
| `llm.ollama.temperature` | 温度参数 (0.0-2.0) | `0.7` |
| `llm.ollama.top_p` | 核采样概率 (0.0-1.0) | `0.8` |
| `llm.ollama.top_k` | Top-K 采样 | `20` |
| `llm.ollama.min_p` | 最小概率阈值 | `0.0` |
| `llm.ollama.presence_penalty` | 存在惩罚 | `1.5` |
| `llm.ollama.repetition_penalty` | 重复惩罚 | `1.0` |
| `llm.ollama.enable_thinking` | 是否启用思维链 | `false` |

### 2. 添加模型到数据库

在 `model` 表中添加 Ollama 模型记录：

```sql
INSERT INTO model (model_name, context_window, supports_tools, note)
VALUES ('qwen2.5:7b', 32768, 1, 'Ollama 本地 Qwen2.5 7B');
```

**注意**：`supports_tools` 必须为 `1`，否则模型不会在剧本智能体中显示。

### 3. 关联 vendor_model

在 `vendor_model` 表中建立关联（`vendor_id=3` 为 Ollama）：

```sql
INSERT INTO vendor_model (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold)
VALUES (3, <model_id>, 0, 0, 0);  -- 本地模型不计费
```

## 支持的模型

以下模型支持 Tool Calling，推荐用于剧本智能体：

| 模型 | 参数量 | 推荐显存 |
|------|--------|----------|
| `qwen2.5:7b` | 7B | 8GB |
| `qwen2.5:14b` | 14B | 16GB |
| `llama3.1:8b` | 8B | 8GB |
| `llama3.1:70b` | 70B | 48GB+ |
| `mistral:7b` | 7B | 8GB |

## 注意事项

1. **Tool Calling 支持**：剧本智能体依赖 Tool Calling 功能，请确保使用支持此功能的模型
2. **性能考虑**：本地模型响应速度取决于硬件配置
3. **显存要求**：7B 模型建议至少 8GB 显存，14B+ 模型需要更多

## 故障排查

### 模型不显示在列表中

1. 检查 `llm.ollama.enabled` 是否为 `true`
2. 检查 `model` 表中 `supports_tools` 是否为 `1`
3. 检查 `vendor_model` 表中是否有 `vendor_id=2` 的记录

### 调用失败

1. 确认 Ollama 服务正在运行：`ollama serve`
2. 检查 `base_url` 配置是否正确
3. 查看日志文件 `logs/llm_api.log` 获取详细错误信息

## 相关文件

| 文件 | 说明 |
|------|------|
| `llm/ollama_client.py` | Ollama 客户端实现 |
| `llm/llm_client_factory.py` | LLM 客户端工厂 |
| `config/default_configs.py` | Ollama 配置定义 |
| `model/model.py` | 模型表定义 |
