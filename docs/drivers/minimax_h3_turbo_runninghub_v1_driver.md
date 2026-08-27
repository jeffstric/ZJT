# MiniMax H3 图生视频「加速版」 RunningHub 驱动

## 概述

MiniMax H3 图生视频**加速版**，通过 RunningHub AI-App 接口调用加速版**首尾帧图生视频**工作流。

- **webapp_id**: `2092199541612306434`

## 与标准版的差异

加速版是任务 `MiniMax H3`（type=34）的**第二个实现方**，与标准版（`minimax_h3_runninghub_v1_driver.md`）同任务共存，用户可在 admin「实现方管理」中切换。

| 项 | 标准版 | 加速版 |
|----|--------|--------|
| 实现名 | `minimax_h3_runninghub_v1`（ID 65） | `minimax_h3_turbo_runninghub_v1`（ID 71） |
| webapp_id | `2086436470516174849` | `2092199541612306434` |
| 尾帧图片节点 | nodeId 145 | **nodeId 146** |
| 驱动类 | `MinimaxH3RunninghubV1Driver` | `MinimaxH3TurboRunninghubV1Driver` |
| 驱动文件 | `task/visual_drivers/minimax_h3_runninghub_v1_driver.py` | `task/visual_drivers/minimax_h3_turbo_runninghub_v1_driver.py` |

其余（参数、接口、提示词优化、配置项）与标准版完全一致。

## 架构定位

- **供应商**: RunningHub (`TaskProvider.RUNNINGHUB`)
- **任务类型**: `TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO = 34`
- **实现驱动**: `DriverImplementation.MINIMAX_H3_TURBO_RUNNINGHUB_V1 = 'minimax_h3_turbo_runninghub_v1'`
- **默认实现方**: 仍为标准版（`implementation` 字段），加速版在 `implementations` 可选列表中

## 支持的参数

| 参数 | 说明 | 默认值 | 可选值 |
|------|------|--------|--------|
| 首帧图片 | 必填 | - | - |
| 尾帧图片 | 可选 | None | - |
| 时长 | 秒 | 5 | 4, 5, 6, 7, 8, 9, 10 |
| 比例 | 视频比例 | 9:16 | 9:16, 16:9, 1:1, 4:3, 3:4 |
| 分辨率 | 清晰度（影响算力，480P=720P×0.42） | 720P | 480P, 720P |
| 提示词 | 文本；提交前会经 `h3_prompt_optimize` 改写成 I2VA/FL2VA 规范，原文备份在 `extra_config.original_prompt` | "" | - |

> **算力**：当前与标准版共用算力表 `{4:5, 5:6, 6:8, 7:9, 8:10, 9:11, 10:13}`（720P 基准），后续如需独立定价可在 admin 后台修改。

## 工作流节点映射

| 参数 | nodeId | fieldName | 说明 |
|------|--------|-----------|------|
| 提示词 | 143 | text | CR Text |
| 首帧图片 | 114 | image | LoadImage |
| 尾帧图片 | **146** | image | LoadImage（**始终传，无尾帧时留空**） |
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

> 加速版工作流的 aspect_ratio COMBO 实际包含 8 个选项（另有 2:3/3:2/21:9），当前仅开放与标准版一致的 5 个；未开放比例会回落到默认 9:16。

## 接口调用

### 提交任务

**POST** `/openapi/v2/run/ai-app/2092199541612306434`

请求体：
```json
{
  "nodeInfoList": [
    {"nodeId": "143", "fieldName": "text", "fieldValue": "提示词", "description": "text"},
    {"nodeId": "114", "fieldName": "image", "fieldValue": "首帧标识", "description": "image"},
    {"nodeId": "146", "fieldName": "image", "fieldValue": "尾帧标识", "description": "image"},
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
