# Seedance 火山引擎供应商驱动 (seedance_volcengine_v1)

## 概述

`seedance_volcengine_v1_driver.py` 实现了调用火山引擎 Seedance 系列图生视频模型的驱动，支持异步 API（创建任务后轮询状态）。

## 支持的模型

| Task ID | 模型名称 | 实现类 | 支持的图片模式 | 支持参考音频/视频 |
|---------|---------|--------|---------------|-----------------|
| 21 | doubao-seedance-1-5-pro-251215 | `Seedance15ProVolcengineV1Driver` | first_last_frame | 支持 |
| 22 | doubao-seedance-2-0-fast-260128 | `Seedance20FastVolcengineV1Driver` | first_last_frame, multi_reference | 支持 |
| 23 | doubao-seedance-2-0-260128 | `Seedance20VolcengineV1Driver` | first_last_frame, multi_reference | 支持 |
| 31 | doubao-seedance-2-0-mini-260615 | `Seedance20MiniVolcengineV1Driver` | first_last_frame, multi_reference | 支持 |

> **Seedance 2.0 Mini**：价格为 Seedance 2.0 的一半，功能与 Seedance 2.0 一致。

## 720p 默认算力配置

Seedance 2.0 系列默认算力按 720p、输入包含视频且输入视频 15 秒的最高成本计算，换算规则为 `1 算力 = 0.04 元`，使用向上取整保证不亏本。国内版和海外版实现方使用同一组默认算力。

| 输出时长 | seedance-2.0 | seedance-2.0-fast | seedance-2.0-mini |
|---------:|-------------:|------------------:|------------------:|
| 5 秒 | 303 | 238 | 152 |
| 6 秒 | 318 | 250 | 159 |
| 7 秒 | 333 | 262 | 167 |
| 8 秒 | 348 | 274 | 174 |
| 9 秒 | 363 | 285 | 182 |
| 10 秒 | 378 | 297 | 189 |
| 11 秒 | 393 | 309 | 197 |
| 12 秒 | 409 | 321 | 204 |
| 13 秒 | 424 | 333 | 212 |
| 14 秒 | 439 | 345 | 220 |
| 15 秒 | 454 | 357 | 227 |

## 特性

- **异步接口**：提交任务后返回 `project_id`，通过轮询 `check_status` 获取结果
- **多帧支持**：支持首帧（first_frame）、尾帧（last_frame）
- **多参考图**：支持 `multi_reference` 模式下多张参考图（role: reference_image）
- **参考视频**：支持传入参考视频（role: reference_video）
- **参考音频**：支持传入参考音频（role: reference_audio）
- **图片压缩上传**：本地图片自动压缩后上传至 CDN

## Content 数组格式

Seedance API 使用 content 数组传递输入：

```json
{
  "model": "doubao-seedance-2-0-260128",
  "content": [
    {"type": "text", "text": "视频描述提示词"},
    {"type": "image_url", "image_url": {"url": "首帧图URL"}, "role": "first_frame"},
    {"type": "image_url", "image_url": {"url": "尾帧图URL"}, "role": "last_frame"},
    {"type": "image_url", "image_url": {"url": "参考图1URL"}, "role": "reference_image"},
    {"type": "image_url", "image_url": {"url": "参考图2URL"}, "role": "reference_image"},
    {"type": "video_url", "video_url": {"url": "参考视频URL"}, "role": "reference_video"},
    {"type": "audio_url", "audio_url": {"url": "参考音频URL"}, "role": "reference_audio"}
  ],
  "duration": 5,
  "ratio": "9:16",
  "generate_audio": false,
  "watermark": false
}
```

### 角色说明

| 角色 | 类型 | 说明 |
|------|------|------|
| `first_frame` | image_url | 视频首帧图片 |
| `last_frame` | image_url | 视频尾帧图片 |
| `reference_image` | image_url | 参考图片（可多张） |
| `reference_video` | video_url | 参考视频 |
| `reference_audio` | audio_url | 参考音频 |

## 参考音频/视频数据来源

参考音频和参考视频优先从 `ai_tool` 模型字段读取，向后兼容 `extra_config`：

1. **参考视频**：优先读取 `ai_tool.video_path`，备选 `extra_config.reference_video`
2. **参考音频**：优先读取 `ai_tool.audio_path`，备选 `extra_config.reference_audio`

## 配置

在 `config.yml` 中添加火山引擎配置：

```yaml
volcengine:
  api_key: "your_volcengine_api_key"
```

## 文件列表

| 文件 | 说明 |
|------|------|
| `task/visual_drivers/seedance_volcengine_v1_driver.py` | 国内版驱动实现 |
| `task/visual_drivers/seedance_volcengine_oversea_v1_driver.py` | 海外版驱动实现 |
| `task/visual_drivers/base_video_driver.py` | 驱动基类 |
| `config/unified_config.py` | 驱动配置定义 |
| `config/constant.py` | 驱动映射配置 |
| `model/ai_tools.py` | AI 工具模型（含 audio_path、video_path 字段） |
