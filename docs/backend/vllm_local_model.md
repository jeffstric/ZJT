# vLLM 本地推理服务支持

本文档介绍如何配置和使用 vLLM 本地推理服务作为剧本智能体的 LLM 后端（`qwen3.8:27b` 模型）。

## 概述

[vLLM](https://github.com/vllm-project/vllm) 是高性能大模型推理框架，对外提供 **OpenAI 兼容 API**（`/v1/chat/completions`）。本系统通过 OpenAI SDK 直接调用 vLLM 服务，与 Ollama 模式同构，但吞吐和长上下文性能更好，适合生产环境本地化部署。

- vLLM 进程由**部署侧外部拉起**（docker / systemd / `vllm serve`），`comfyui_server` 仅做客户端对接，不管理其生命周期
- `qwen3.8:27b` 与 Ollama 供应商**复用同一条 model 记录**，按 vendor 区分：前端模型 ID 分别为 `ollama:qwen3.8:27b` 与 `vllm:qwen3.8:27b`
- 默认**不启用**（`llm.vllm.enabled: false`），需部署好 vLLM 服务后在管理后台开启

## 前置要求

1. 安装 vLLM（需 GPU 环境，CUDA）：

```bash
pip install vllm
```

2. 准备模型权重：从 HuggingFace 拉取（`Qwen/Qwen3.8-27B`），或指定本地权重目录

3. 显存：27B 全精度约需 54GB+；Q4 量化约 24GB 起步（与 Ollama 版一致）

## 启动 vLLM 服务

### 方式一：vllm serve 命令行

```bash
vllm serve Qwen/Qwen3.8-27B \
  --served-model-name qwen3.8:27b \
  --port 8001 \
  --max-model-len 262144 \
  --gpu-memory-utilization 0.9 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3
```

**关键参数说明**：

| 参数 | 说明 |
|------|------|
| `--served-model-name qwen3.8:27b` | **必须**与数据库 `model.model_name` 一致，客户端按此名称请求 |
| `--port 8001` | 主服务默认端口为 8000（`server.port`），vLLM 必须错开，勿用 8000 |
| `--max-model-len 262144` | 对齐模型原生 256K 上下文 |
| `--enable-auto-tool-choice` + `--tool-call-parser qwen3_coder` | **必须**，剧本智能体依赖 Tool Calling |
| `--reasoning-parser qwen3` | **必须**，将 Qwen3 思考内容解析到 `reasoning_content` 字段；缺失时思考内容混入正文，可能耗尽输出 token 预算 |
| `--gpu-memory-utilization` | 按显存余量调整（默认 0.9） |

### 方式二：docker

```bash
docker run --gpus all -p 8001:8000 \
  -v /path/to/models:/models \
  vllm/vllm-openai:latest \
  /models/Qwen3.8-27B \
  --served-model-name qwen3.8:27b \
  --max-model-len 262144 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3
```

容器内端口固定为 8000，宿主机侧映射到 8001。

### 健康检查

```bash
curl http://localhost:8001/v1/models
# 应返回 {"data":[{"id":"qwen3.8:27b", ...}]}
```

## 配置步骤

### 1. 启用 vLLM

在 `config.yml` 中配置：

```yaml
llm:
  vllm:
    enabled: true
    base_url: "http://localhost:8001"
    # 模型参数配置（默认值对齐 Qwen3.8 官方思考模式推荐值）
    temperature: 1.0
    top_p: 0.95
    top_k: 20
    min_p: 0.0
    presence_penalty: 0.0
    repetition_penalty: 1.0
    enable_thinking: true
```

或在管理后台的「快速配置」中启用和调整参数：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `llm.vllm.enabled` | 是否启用 | `false` |
| `llm.vllm.base_url` | vLLM 服务地址 | `http://localhost:8001` |
| `llm.vllm.temperature` | 温度参数 (0.0-2.0) | `1.0` |
| `llm.vllm.top_p` | 核采样概率 (0.0-1.0) | `0.95` |
| `llm.vllm.top_k` | Top-K 采样 | `20` |
| `llm.vllm.min_p` | 最小概率阈值 | `0.0` |
| `llm.vllm.presence_penalty` | 存在惩罚 | `0.0` |
| `llm.vllm.repetition_penalty` | 重复惩罚 | `1.0` |
| `llm.vllm.enable_thinking` | 是否启用思维链 | `true` |

### 2. 数据库（已由迁移自动完成）

`alembic/versions/20260825_add_vllm_qwen38_27b.py` 已写入：

- `vendor` 表：`vllm` 供应商
- `vendor_model` 表：`vllm` × `qwen3.8:27b` 计费阈值（input=200000 / out=10000 / cache=100000，与 Ollama 同名模型一致）
- `model` 表：`qwen3.8:27b` 记录由 `20260822_add_ollama_qwen38_27b.py` 写入，两个供应商共用，**无需重复插入**

升级数据库：`alembic upgrade head`

## 系统已接入的模型

| 模型 | 上下文窗口 | 最大输出 | 能力 | 备注 |
|------|-----------|---------|------|------|
| `qwen3.8:27b` | 262,144（原生，可扩至 1M） | 131,072 | 工具 / 思考 / 视觉 | 前端模型 ID `vllm:qwen3.8:27b` |

`qwen3.8:27b` 官方推荐采样（[HuggingFace Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)）：

| 模式 | temperature | top_p | top_k | min_p | presence_penalty | repetition_penalty |
|------|-------------|-------|-------|-------|------------------|--------------------|
| 思考模式（系统默认） | 1.0 | 0.95 | 20 | 0.0 | 0.0 | 1.0 |
| Instruct / 非思考 | 0.7 | 0.80 | 20 | 0.0 | 1.5 | 1.0 |

客户端通过 `extra_body.chat_template_kwargs.enable_thinking` 下发思考开关（Qwen3 官方 chat template 原生支持），思考内容从响应 `reasoning_content` 字段提取。思考开启时还会下发 `reasoning_effort`（low/medium/xhigh，Qwen 官方模型卡参数名），由前端思考强度 `thinking_effort` 映射而来（前端 "high" 映射为 "xhigh"）。

## 计费说明

与 Ollama 同名模型阈值一致（1 点算力 = 0.04 元）：

- 输入：200,000 token / 点
- 输出：10,000 token / 点
- 缓存读：100,000 token / 点（vLLM 开启 prefix caching 时，缓存命中量从 `usage.prompt_tokens_details.cached_tokens` 提取并计入）

## 注意事项

1. **端口冲突**：主服务默认监听 8000，vLLM 必须使用其他端口（推荐 8001）
2. **served-model-name**：启动 vLLM 时必须设置 `--served-model-name qwen3.8:27b`，否则模型名与数据库不一致导致 404
3. **Tool Calling**：必须启用 `--enable-auto-tool-choice --tool-call-parser qwen3_coder`，否则剧本智能体的工具调用会失败
4. **思考模式解析**：必须启用 `--reasoning-parser qwen3`，否则思考内容混入正文，既污染结果又可能耗尽输出 token 预算
5. **显存要求**：27B 模型 Q4 量化约需 24GB 显存起步；与 Ollama 同时部署时注意显存分配
6. **缓存命中计费**：vLLM 默认开启 prefix caching，长会话缓存命中可显著降低成本

## 故障排查

### 模型不显示在列表中

1. 检查 `llm.vllm.enabled` 是否为 `true`
2. 检查 `vendor` 表是否有 `vendor_name='vllm'` 记录（迁移是否执行）
3. 检查 `vendor_model` 表是否有 vllm × `qwen3.8:27b` 关联
4. 检查 `model` 表 `qwen3.8:27b` 的 `supports_tools` 是否为 `1`

### 调用失败（connection error）

1. 确认 vLLM 服务正在运行：`curl http://localhost:8001/v1/models`
2. 检查 `llm.vllm.base_url` 配置是否正确（含端口）
3. 查看日志文件 `logs/llm_api.log` 获取详细错误信息

### 调用返回 404 model not found

`--served-model-name` 与数据库 `model_name` 不一致，重启 vLLM 并修正参数

## 相关文件

| 文件 | 说明 |
|------|------|
| `llm/vllm_client.py` | vLLM 客户端实现 |
| `llm/llm_client_factory.py` | LLM 客户端工厂（含本地服务前缀路由） |
| `config/constant.py` | `LLMVendor.VLLM` / `LLMModel.VLLM_QWEN_3_8_27B` 常量 |
| `config/default_configs.py` | vLLM 热更新配置定义 |
| `config/default_vendor_model_billing.py` | vLLM 默认计费阈值 |
| `alembic/versions/20260825_add_vllm_qwen38_27b.py` | vLLM 供应商与计费迁移 |
| `docs/backend/ollama_local_model.md` | Ollama 本地模型文档（对照参考） |
