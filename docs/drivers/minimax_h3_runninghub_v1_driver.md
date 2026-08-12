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

type=34 创建后会挂 `param_prepare` 步骤 `h3_prompt_optimize`（见 `docs/backend/pipeline_steps.md`）：

- 仅首帧走 I2VA，有尾帧走 FL2VA
- 改写模板：`task/pipeline_drivers/prompts/minimax_h3_i2va_fl2va_base_en.txt`
- 驱动读 `extra_config.h3_prompt_optimize.optimized_prompt`，否则读 `ai_tool.prompt`
- 关闭开关或 LLM 失败时回退原文，仍提交 RunningHub

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
