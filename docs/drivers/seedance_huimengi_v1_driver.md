# Seedance huimengi（慧梦）网关驱动

## 概述

huimengi（慧梦）是 Seedance 2.0 系列的二次封装网关，与火山引擎国内版、海外版、kkidc
网关并列，作为现有 Seedance 2.0 / 2.0 Fast / 2.0 Mini 三类图生视频任务的**第 4 个实现方**。

huimengi 的接口结构与火山原生、kkidc 完全不同：

| 维度 | 火山原生 | kkidc | huimengi |
|------|----------|-------|----------|
| 请求体 | `content[]` 数组 | 扁平 `prompt` + `metadata{}` | 扁平 `{model, params{}}` |
| 创建路径 | `/api/v3/contents/generations/tasks` | `/v1/video/generations` | `/api/v1/tasks` |
| 查询路径 | `/api/v3/contents/generations/tasks/{id}` | `/v1/video/generations/{id}` | `/api/v1/tasks/{id}` |
| 提交响应 | 扁平 `{id, ...}` | 三段式 `{code,message,data{}}` | 扁平 `{task_id, status}` |
| 查询响应 | 扁平 `{id, status, content.video_url}` | 三段式 + 嵌套 `data.data` | 扁平 `{id, status, result.video_url}` |
| 模型名 | `doubao-seedance-*-26xxxx` | `seed-2` / `seed-2-fast` / `seed-2-mini` | `seedance-2.0` / `seedance-2.0-fast` / `seedance-2.0-mini` |

接口结构差异显著，故独立实现驱动 `seedance_huimengi_v1_driver.py`，不复用 kkidc 驱动代码。

## 架构定位

- **复用** `TaskTypeId`（22 = Fast / 23 = 2.0 / 31 = Mini）、`DriverKey`、`TaskProvider`
  （VOLCENGINE）、`power_modifiers`（分辨率倍率）
- **无需数据库迁移**：huimengi 仅是现有 Seedance 任务的新实现方
- `sort_order` 使用 11010 / 11020 / 11030（kkidc 为 10910 / 10920 / 10930）
- 当 `huimengi.api_key` 未配置时，实现方自动隐藏（由 `required_config_keys` 控制）

## 支持的模型

| TaskTypeId | huimengi 模型名 | 实现类 | DriverImplementation | ID |
|------------|-----------------|--------|----------------------|----|
| 22 | seedance-2.0-fast | `Seedance20FastHuimengiV1Driver` | `seedance_2_0_fast_huimengi_v1` | 62 |
| 23 | seedance-2.0 | `Seedance20HuimengiV1Driver` | `seedance_2_0_huimengi_v1` | 63 |
| 31 | seedance-2.0-mini | `Seedance20MiniHuimengiV1Driver` | `seedance_2_0_mini_huimengi_v1` | 64 |

## 配置项

| 配置键 | 类型 | 必填 | 敏感 | 说明 |
|--------|------|------|------|------|
| `huimengi.api_key` | string | 是 | 是 | huimengi 网关 API Key |
| `huimengi.base_url` | string | 否 | 否 | API 基础 URL（默认 `https://api.huimengi.com`） |

均支持管理后台热更新（`quick_config: True`）。

## 接口规格

### 鉴权

通过 `Authorization` 请求头传入 API Key：

```
Authorization: Bearer hm-xxxxxxxxxxxxxxxx
```

### 创建任务

**POST** `/api/v1/tasks`

请求体结构（扁平 `{model, params}`）：

```json
{
  "model": "seedance-2.0",
  "params": {
    "prompt": "一只猫在海滩上漫步",
    "duration": 5,
    "ratio": "16:9",
    "resolution": "720p",
    "generate_audio": true,
    "human_review": false
  }
}
```

不同模式的 params 字段差异：

| 模式 | 额外 params 字段 |
|------|-----------------|
| 文生视频 | 仅 prompt + 控制字段 |
| 首帧图生视频 | `image_url` |
| 首尾帧图生视频 | `first_frame_image` + `last_frame_image` |
| 多参考图 | `reference_images[]` + 可选 `reference_videos[]` / `reference_audios[]` |

提交成功响应：

```json
{
  "task_id": "a820e1b8-fb15-4ec9-a13c-bdd1d4eb6679",
  "status": "pending"
}
```

### 查询任务

**GET** `/api/v1/tasks/{task_id}`

成功响应：

```json
{
  "id": "a820e1b8-...",
  "model": "seedance-2.0",
  "status": "completed",
  "result": {
    "video_url": "https://...",
    "duration": 5,
    "resolution": "720p",
    "ratio": "16:9"
  },
  "cost": 1.55,
  "created_at": "2026-04-24T10:00:00",
  "completed_at": "2026-04-24T10:01:20"
}
```

失败响应：

```json
{
  "id": "a820e1b8-...",
  "status": "failed",
  "error_message": "错误原因",
  "cost": 0
}
```

### 状态映射

| huimengi status | 内部状态 | 处理 |
|-----------------|----------|------|
| `pending` | RUNNING | 等待生成 |
| `processing` | RUNNING | 生成中 |
| `completed` | SUCCESS | 取 `result.video_url` |
| `failed` | FAILED | 取 `error_message` |

### params 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ratio` | string | 否 | 宽高比，默认 adaptive，可选 16:9 / 4:3 / 1:1 / 3:4 / 9:16 / 21:9 / adaptive |
| `prompt` | string | 是 | 视频描述文本（建议 500 字以内） |
| `duration` | integer | 否 | 视频时长（秒），取值 [4, 15]，默认 5 |
| `image_url` | string | 否 | 首帧图片 URL（图生视频-首帧） |
| `resolution` | string | 否 | 分辨率，默认 720p，可选 480p / 720p / 1080p / 4k |
| `human_review` | boolean | 否 | 真人审核模式，默认 false |
| `generate_audio` | boolean | 否 | 是否生成同步音频，默认 true |
| `last_frame_image` | string | 否 | 尾帧图片 URL（图生视频-首尾帧） |
| `reference_audios` | array | 否 | 参考音频 URL 列表（0-3 段，总时长不超过 15s） |
| `reference_images` | array | 否 | 参考图片 URL 列表（1-9 张） |
| `reference_videos` | array | 否 | 参考视频 URL 列表（0-3 个，总时长不超过 15s） |
| `first_frame_image` | string | 否 | 首帧图片 URL（图生视频-首尾帧） |

## 错误处理策略

| 场景 | 处理 | retry |
|------|------|-------|
| HTTP 400 内容审核 | 走 `format_user_facing_moderation_error` 返回友好文案 | False |
| HTTP 400 参数错误 | 返回 API 错误文案 | False |
| HTTP 429 限流 | "上游限流，请稍后重试" | True |
| 网络错误（Connection/Timeout） | "网络连接异常，请稍后重试" | True |
| 响应格式异常 | Sentry 报警 + "服务异常，请联系技术支持" | False |

> 关键实现点：基类 `_request` 在 `raise_for_status()` 时会丢弃响应体，
> huimengi 驱动通过 `_extract_http_error_body()` 从 HTTPError 重新解析错误体，
> 与 kkidc 驱动一致。

## 特性

- ✅ 文生视频（t2v）
- ✅ 首帧图生视频（`image_url`）
- ✅ 首尾帧图生视频（`first_frame_image` + `last_frame_image`）
- ✅ 多参考图（含参考音视频）
- ✅ 真人审核模式（`human_review` 透传）
- ✅ face_mask / image_face_mask pipeline 结果替换（避免真人审核不通过）
- ✅ 参考视频规范化（帧率限制，复用 `prepare_seedance_reference_video_sync`）
- ✅ 分辨率小写映射（480p / 720p / 1080p / 4k）

## 参考视频帧率限制

参考视频（r2v）复用火山版的三层帧率防御（与 kkidc 一致）：
1. 前端节流
2. 后端 ffmpeg `-fpsmax`
3. 上传时 ffprobe 检查

目标 30fps，上限 60fps。
