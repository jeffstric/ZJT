# Ollama 本地模型支持

本文档介绍如何配置和使用 Ollama 本地模型作为剧本智能体的 LLM 后端。

## 概述

Ollama 是一个本地运行大语言模型的工具，支持 Llama、Qwen、Mistral 等多种开源模型。本系统支持通过 Ollama 的 OpenAI 兼容接口调用本地模型。

## 前置要求

1. 安装 Ollama：https://ollama.ai
2. 下载支持 Tool Calling 的模型（系统已接入 `qwen3.8:27b`、`qwen3.6:35b-a3b`）

```bash
# 系统已接入的 Ollama 模型
ollama pull qwen3.8:27b
ollama pull qwen3.6:35b-a3b

# 其他支持 Tool Calling 的示例
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
    enable_thinking: true
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
| `llm.ollama.enable_thinking` | 是否启用思维链 | `true` |

### 2. 添加模型到数据库

`qwen3.8:27b`、`qwen3.6:35b-a3b` 已由 Alembic 迁移写入。若要自行接入其他 Ollama 模型：

```sql
INSERT INTO model (model_name, context_window, supports_tools, max_output_tokens, supports_thinking, supports_vl, note)
VALUES ('qwen2.5:7b', 32768, 1, 64000, 0, 0, 'Ollama 本地 Qwen2.5 7B');
```

**注意**：`supports_tools` 必须为 `1`，否则模型不会在剧本智能体中显示。

### 3. 关联 vendor_model

在 `vendor_model` 表中建立关联（`vendor_id` 请按 `vendor_name='ollama'` 查询，勿写死）：

```sql
INSERT INTO vendor_model (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold)
SELECT v.id, m.id, 200000, 10000, 100000
FROM vendor v, model m
WHERE v.vendor_name = 'ollama' AND m.model_name = 'qwen2.5:7b';
```

## 系统已接入的模型

| 模型 | 上下文窗口 | 最大输出 | 能力 | 推荐显存 |
|------|-----------|---------|------|----------|
| `qwen3.8:27b` | 262,144（原生，可扩至 1M） | 131,072 | 工具 / 思考 / 视觉 | 24GB（Q4_K_M 约 18GB） |
| `qwen3.6:35b-a3b` | 250,000 | 默认 64,000 | 工具 / 思考 / 视觉 | 24GB+ |

前端与 API 中的模型 ID 为 `ollama:qwen3.8:27b`（Ollama 供应商会自动加 `ollama:` 前缀）。

`qwen3.8:27b` 官方推荐采样（[HuggingFace Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)、[Ollama qwen3.8:27b](https://ollama.com/library/qwen3.8:27b)）：

| 模式 | temperature | top_p | top_k | min_p | presence_penalty | repetition_penalty |
|------|-------------|-------|-------|-------|------------------|--------------------|
| 思考模式（模型默认开启） | 1.0 | 0.95 | 20 | 0.0 | 0.0 | 1.0 |
| Instruct / 非思考 | 0.7 | 0.80 | 20 | 0.0 | 1.5 | 1.0 |

系统默认 `llm.ollama.enable_thinking: true`，Ollama 调用会开启思维链（`qwen3.8:27b` 官方默认即为思考模式）。开启思考时建议把 temperature / top_p / presence_penalty 改成上表思考模式参数。思考开关以「调用方显式传入的 `enable_thinking`（True/False）优先，未传时回退全局配置」为准；若要全局关闭，在管理后台将 `llm.ollama.enable_thinking` 设为 `false`。

思考强度由任务的 `thinking_effort`（low/medium/high）映射为 chat template 的 `reasoning_effort`（low/medium/xhigh，Qwen 官方参数名，前端 "high" 映射为 "xhigh"）下发；多轮对话默认保留历史思考块（`preserve_thinking`）。

## 其他支持 Tool Calling 的模型

以下模型支持 Tool Calling，可按「添加模型到数据库」自行接入：

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
