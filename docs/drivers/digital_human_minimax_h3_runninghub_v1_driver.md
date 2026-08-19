# MiniMax H3 数字人 RunningHub 驱动

## 概述

通过 RunningHub AI-App 接口调用 **MiniMax H3 数字人**工作流：输入人物图片 + 说话音频 + 动作提示词，生成对口型数字人视频。

- **webapp_id**: `2087200340012785665`
- **任务类型**: `TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3 = 35`
- **实现驱动**: `DriverImplementation.DIGITAL_HUMAN_MINIMAX_H3_RUNNINGHUB_V1 = 'digital_human_minimax_h3_runninghub_v1'`
- **驱动文件**: `task/visual_drivers/digital_human_minimax_h3_runninghub_v1_driver.py`
- **前端入口**: 首页 → 数字人 → `MiniMax H3 数字人` 页签
- **提交 API**: `POST /api/digital-human-minimax-h3`

## 支持的参数

| 参数 | 说明 | 默认值 | 可选值 |
|------|------|--------|--------|
| 图片 | 必填，人物形象图 | - | - |
| 音频 | 必填，说话音频 | - | - |
| 提示词 | 必填，动作描述 | - | 最多 1000 字 |
| 时长 | 视频时长（秒） | 10 | 4, 5, 6, 7, 8, 9, 10 |
| 最长边 | 视频最长边像素 | 1280 | 720, 1280, 1920 |
| 开始说话秒数 | 数字人从第几秒开始说话 | 0 | ≥ 0 的整数 |

## 工作流节点映射

| 参数 | nodeId | fieldName | 说明 |
|------|--------|-----------|------|
| 提示词 | 214 | value | 动作描述文本 |
| 音频 | 215 | audio | RunningHub fileName |
| 图片 | 209 | image | RunningHub 图床 URL / fileName |
| 时长 | 212 | value | 秒（字符串） |
| 最长边 | 213 | value | 像素（字符串） |
| 开始说话秒数 | 229 | value | 秒（字符串） |

## 数据存储

- `ai_tools.type = 35`
- `ai_tools.image_path`：本地图片路径
- `ai_tools.audio_path`：本地音频路径
- `ai_tools.duration`：视频时长
- `ai_tools.prompt`：提示词
- `ai_tools.extra_config`：`{"max_edge": 1280, "start_second": 0}`

## 算力

基准与 MiniMax H3 图生视频一致，按时长计费（实现方 `default_computing_power`）：

| 时长(秒) | 算力 |
|----------|------|
| 4 | 5 |
| 5 | 6 |
| 6 | 8 |
| 7 | 9 |
| 8 | 10 |
| 9 | 11 |
| 10 | 13 |

## 接口调用

### 提交任务

**POST** `/openapi/v2/run/ai-app/2087200340012785665`

```json
{
  "nodeInfoList": [
    {"nodeId": "214", "fieldName": "value", "fieldValue": "图片1中的角色在唱歌。", "description": "value"},
    {"nodeId": "215", "fieldName": "audio", "fieldValue": "<audio_fileName>", "description": "audio"},
    {"nodeId": "209", "fieldName": "image", "fieldValue": "<image_fileName>", "description": "image"},
    {"nodeId": "212", "fieldName": "value", "fieldValue": "10", "description": "value"},
    {"nodeId": "213", "fieldName": "value", "fieldValue": "1280", "description": "value"},
    {"nodeId": "229", "fieldName": "value", "fieldValue": "0", "description": "value"}
  ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}
```

### 查询状态 / 获取结果

- **POST** `/task/openapi/status` — body: `{"apiKey", "taskId"}`
- **POST** `/task/openapi/outputs` — body: `{"apiKey", "taskId"}`，返回 `data[].fileUrl`（mp4）

## 配置项

依赖 RunningHub 动态配置：

- `runninghub.api_key`
- `runninghub.host`

## 前端页签

数字人页面三个模型：

1. wan2.2 数字人（type=13）
2. LTX2.3 数字人（type=32）
3. **MiniMax H3 数字人（type=35）** ← 本驱动
