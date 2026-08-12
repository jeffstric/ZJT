# MiniMax H3 参考生视频驱动 (minimax_h3_reference_runninghub_v1)

## 概述

通过 RunningHub AI-App 接口调用「MiniMax H3 多参生视频」工作流，支持最多 9 张参考图生成视频。

- **webapp_id**：`2084224746308325377`
- **任务类型**：TaskTypeId.MINIMAX_H3_REFERENCE_TO_VIDEO = 36
- **DriverKey**：`minimax_h3_reference_to_video`
- **实现方**：`minimax_h3_reference_runninghub_v1`（id=67）
- **驱动类**：`MinimaxH3ReferenceRunninghubV1Driver`
- **图片模式**：多参考图模式（`multi_reference`），最多 9 张
- **查询接口**：`/task/openapi/status` + `/task/openapi/outputs`（与首尾帧版一致）

## 支持的参数

| 参数 | 说明 | 默认值 | 可选值 |
|------|------|--------|--------|
| 参考图 | 必填，1~9 张 | - | - |
| 时长 | 秒 | 5 | 4, 5, 6, 7, 8, 9, 10 |
| 比例 | 视频比例 | 9:16 | 9:16, 16:9, 1:1, 4:3, 3:4, 2:3, 3:2, 21:9 |
| 分辨率 | 清晰度（影响算力，480P=720P×0.42） | 720P | 480P, 720P |
| 提示词 | 文本 | "" | - |

> **算力**：基准为 720P（1 算力 ≈ 13 R币），480P 为 720P 的 42%（通过分辨率倍率 `MINIMAX_H3_480P_PRICE_MULTIPLIER=0.42`）。
> 与首尾帧版共用算力表。

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

## 工作流节点映射

| 参数 | nodeId | fieldName | 说明 |
|------|--------|-----------|------|
| 参考图1 | 137 | image | LoadImage |
| 参考图2 | 139 | image | LoadImage |
| 参考图3 | 142 | image | LoadImage |
| 参考图4 | 147 | image | LoadImage |
| 参考图5 | 149 | image | LoadImage |
| 参考图6 | 150 | image | LoadImage |
| 参考图7 | 151 | image | LoadImage |
| 参考图8 | 152 | image | LoadImage |
| 参考图9 | 153 | image | LoadImage |
| 提示词 | 138 | value | 文本 |
| 时长 | 132 | value | INTConstant（秒） |
| 比例 | 115 | aspect_ratio | ResolutionSelector（带括号文本，带 fieldData） |
| 分辨率 | 115 | megapixels | ResolutionSelector（0.4/0.9） |

> **参考图填充规则**：用户传 N 张图时，按顺序填入前 N 个节点（上传后的图标识），剩余 9-N 个节点 `fieldValue` 留空（避免 RunningHub 用节点默认值）。
> 参考图固定 nodeId 列表（顺序敏感）：`["137","139","142","147","149","150","151","152","153"]`。

## 分辨率映射

复用首尾帧版 `MINIMAX_H3_DRIVER_VALUES`：

| 标准分辨率 | megapixels |
|------------|-----------|
| 480P | 0.4 |
| 720P（默认） | 0.9 |

> 注：工作流接口默认 megapixels=0.6（608×1056），本驱动按 480P/720P 标准档下发 0.4/0.9。

## 比例映射

| 比例 | aspect_ratio fieldValue |
|------|-------------------------|
| 1:1 | 1:1 (Square) |
| 16:9 | 16:9 (Widescreen) |
| 9:16 | 9:16 (Portrait Widescreen) |
| 4:3 | 4:3 (Standard) |
| 3:4 | 3:4 (Portrait Standard) |
| 2:3 | 2:3 (Portrait Photo) |
| 3:2 | 3:2 (Photo) |
| 21:9 | 21:9 (Ultrawide) |

## 接口调用

### 提交任务

**POST** `/openapi/v2/run/ai-app/2084224746308325377`

请求体（示例：3 张参考图）：
```json
{
  "nodeInfoList": [
    {"nodeId": "137", "fieldName": "image", "fieldValue": "参考图1标识", "description": "图1"},
    {"nodeId": "139", "fieldName": "image", "fieldValue": "参考图2标识", "description": "图2"},
    {"nodeId": "142", "fieldName": "image", "fieldValue": "参考图3标识", "description": "图3"},
    {"nodeId": "147", "fieldName": "image", "fieldValue": "", "description": "图4"},
    {"nodeId": "149", "fieldName": "image", "fieldValue": "", "description": "图5"},
    {"nodeId": "150", "fieldName": "image", "fieldValue": "", "description": "图6"},
    {"nodeId": "151", "fieldName": "image", "fieldValue": "", "description": "图7"},
    {"nodeId": "152", "fieldName": "image", "fieldValue": "", "description": "图8"},
    {"nodeId": "153", "fieldName": "image", "fieldValue": "", "description": "图9"},
    {"nodeId": "138", "fieldName": "value", "fieldValue": "提示词", "description": "提示词"},
    {"nodeId": "132", "fieldName": "value", "fieldValue": "5", "description": "视频秒数"},
    {"nodeId": "115", "fieldName": "aspect_ratio", "fieldData": "...", "fieldValue": "9:16 (Portrait Widescreen)", "description": "长宽比"},
    {"nodeId": "115", "fieldName": "megapixels", "fieldValue": "0.9", "description": "视频分辨率"}
  ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}
```

### 查询状态（与首尾帧版一致）

1. **POST** `/task/openapi/status`，body：`{apiKey, taskId}` → 返回 `data` 状态字符串
2. SUCCESS 后 **POST** `/task/openapi/outputs`，body：`{apiKey, taskId}` → 取首个 `fileUrl`

## 与首尾帧版 (minimax_h3_runninghub_v1) 差异

| 维度 | 首尾帧版 | 参考生视频版 |
|------|---------|-------------|
| webapp_id | 2086436470516174849 | 2084224746308325377 |
| 图片模式 | first_last_frame（首帧+尾帧） | multi_reference（1~9 张参考图） |
| 图片节点 | 114 首帧 / 145 尾帧 | 137/139/142/147/149/150/151/152/153 |
| 提示词节点 | 143 text | 138 value |
| 时长节点 | 136 value | 132 value |
| 比例档位 | 5 档 | 8 档（多 2:3/3:2/21:9） |
| 算力/分辨率/查询接口/上传逻辑 | — | 完全复用 |
