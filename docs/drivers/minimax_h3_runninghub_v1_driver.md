# MiniMax H3 RunningHub 驱动（支持音频版）

## 概述

MiniMax H3 通过 RunningHub AI-App 接口调用**首尾帧图生视频**工作流（支持音频）。

- **webapp_id**: `2086436470516174849`
- **工作流名称**: 支持音频的 H3 图生视频工作流

## 架构定位

- **供应商**: RunningHub (`TaskProvider.RUNNINGHUB`)
- **任务类型**: `TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO = 34`
- **实现驱动**: `DriverImplementation.MINIMAX_H3_RUNNINGHUB_V1 = 'minimax_h3_runninghub_v1'`
- **驱动文件**: `task/visual_drivers/minimax_h3_runninghub_v1_driver.py`

> **多实现方**：本任务含两个实现方可切换（默认标准版）：
> - 标准版 `minimax_h3_runninghub_v1`（ID 65，webapp `2086436470516174849`，尾帧节点 145）
> - 加速版 `minimax_h3_turbo_runninghub_v1`（ID 71，webapp `2092199541612306434`，尾帧节点 146），详见 [minimax_h3_turbo_runninghub_v1_driver.md](minimax_h3_turbo_runninghub_v1_driver.md)

## 支持的参数

| 参数 | 说明 | 默认值 | 可选值 |
|------|------|--------|--------|
| 首帧图片 | 必填 | - | - |
| 尾帧图片 | 可选 | None | - |
| 时长 | 秒 | 5 | 4, 5, 6, 7, 8, 9, 10 |
| 比例 | 视频比例 | 9:16 | 9:16, 16:9, 1:1, 4:3, 3:4 |
| 分辨率 | 清晰度（影响算力，480P=720P×0.42） | 720P | 480P, 720P |
| 提示词 | 文本；提交前会经 `h3_prompt_optimize` 改写成 I2VA/FL2VA 规范，原文备份在 `extra_config.original_prompt` | "" | - |

> **算力**：基准为 720P（1 算力 ≈ 13 R币），480P 为 720P 的 42%（通过分辨率倍率 `MINIMAX_H3_480P_PRICE_MULTIPLIER=0.42`）。
> 工作流要求时长 4~15 秒（`RHMiniMaxH3FL2VATarget` 节点限制）。

### 算力对照表

| 时长(秒) | 720P(基准) | 480P(×0.42) |
|----------|------------|-------------|
| 4 | 5 | 3 |
| 5 | 6 | 3 |
| 6 | 8 | 4 |
| 7 | 9 | 4 |
| 8 | 10 | 5 |
| 9 | 11 | 5 |
| 10 | 13 | 6 |

> 计算公式：`final_power = ceil(default_computing_power[duration] × resolution_multiplier)`，480P 向上取整后低时长档位可能出现相邻档算力相同，属正常现象。

## 提交前提示词优化

type=34 创建时会与 `ai_tool` 在**同一事务**内创建 `param_prepare` 步骤 `h3_prompt_optimize`（见 `docs/backend/pipeline_steps.md`），避免 ai_tool 已落库而步骤尚未创建的竞态。

- 仅首帧走 I2VA，有尾帧走 FL2VA
- 改写模板：`task/pipeline_drivers/prompts/minimax_h3_i2va_fl2va_base_en.txt`
- 驱动读 `extra_config.h3_prompt_optimize.optimized_prompt`，否则读 `ai_tool.prompt`
- 关闭开关或 LLM 失败时回退原文，仍提交 RunningHub
- **对话保真**：描述性文字输出英文，但 `<d>` 内台词/歌词及画面可见文字必须逐字保留原语言（标签按实际语言写，如 `[Chinese]`），严禁翻译；原文含"引号包裹的 CJK 片段"时 user message 追加条件式点名指令，语义判断交给 LLM（详见 `docs/backend/pipeline_steps.md` 的对话保真小节）

### 大模型回退链

优化所用聊天模型按优先级选取（每步校验 api_key 是否已配置，首个可用者胜出）：

1. **故事板对话模型**：故事板入口生成视频时，把用户在该故事板选的对话模型写入步骤参数（`chat_model`/`chat_vendor_id`）
2. **`pipeline.h3_prompt_optimize_model`**（默认 `deepseek-v4-flash`，走官方 DeepSeek `llm.deepseek.api_key`）
3. **JIEKOU 在线模型** `LLMModel.GEMINI_3_5_FLASH`（`gemini-3.5-flash`，走 JIEKOU/google key；2026-08 原第三级"剧本拆分默认模型"随默认值切 `deepseek-v4-flash` 后与第 2 级重复、被去重失效，故改为独立在线模型）

独立图生视频入口（无故事板上下文）跳过第 1 步。全部候选均未配置密钥时直接回退原文，不发起必败的 LLM 调用。

### 超时

- 单次 LLM 调用：`H3_PROMPT_OPTIMIZE_TIMEOUT = 90s`，同时作为外层 `asyncio.wait_for` 与底层 `request_timeout`（对齐 httpx，避免超时后线程残留）
- 失败重试 1 次（共 2 次调用），最坏约 180s 后回退原文

## 工作流节点映射

| 参数 | nodeId | fieldName | 说明 |
|------|--------|-----------|------|
| 提示词 | 143 | text | CR Text |
| 首帧图片 | 114 | image | LoadImage |
| 尾帧图片 | 145 | image | LoadImage（**始终传，无尾帧时留空**） |
| 分辨率 | 115 | megapixels | ResolutionSelector（0.4/0.9） |
| 比例 | 115 | aspect_ratio | ResolutionSelector（带括号文本，带 fieldData） |
| 时长 | 136 | value | INTConstant（秒） |

## 分辨率映射

| 标准分辨率 | megapixels |
|------------|-----------|
| 480P | 0.4 |
| 720P（默认） | 0.9 |

## 比例映射

| 比例 | aspect_ratio fieldValue |
|------|-------------------------|
| 1:1 | 1:1 (Square) |
| 16:9 | 16:9 (Widescreen) |
| 9:16 | 9:16 (Portrait Widescreen) |
| 4:3 | 4:3 (Standard) |
| 3:4 | 3:4 (Portrait Standard) |

## 接口调用

### 提交任务

**POST** `/openapi/v2/run/ai-app/2086436470516174849`

请求体：
```json
{
  "nodeInfoList": [
    {"nodeId": "143", "fieldName": "text", "fieldValue": "提示词", "description": "text"},
    {"nodeId": "114", "fieldName": "image", "fieldValue": "首帧标识", "description": "image"},
    {"nodeId": "145", "fieldName": "image", "fieldValue": "尾帧标识", "description": "image"},
    {"nodeId": "115", "fieldName": "megapixels", "fieldValue": "0.9", "description": "megapixels"},
    {"nodeId": "115", "fieldName": "aspect_ratio", "fieldData": "...", "fieldValue": "9:16 (Portrait Widescreen)", "description": "aspect_ratio"},
    {"nodeId": "136", "fieldName": "value", "fieldValue": "5", "description": "value"}
  ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}
```

### 查询状态 / 获取结果

- **POST** `/task/openapi/status` — body: `{"apiKey", "taskId"}`
- **POST** `/task/openapi/outputs` — body: `{"apiKey", "taskId"}`，返回 `data[].fileUrl`

## 配置项

复用 RunningHub 通用配置：

| 配置键 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `runninghub.api_key` | string | 是 | RunningHub API Key |
| `runninghub.host` | string | 是 | RunningHub API 主机地址 |
