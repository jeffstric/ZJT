# Seedance kkidc 网关驱动 (seedance_kkidc_v1)

## 概述

`seedance_kkidc_v1_driver.py` 实现了调用 **kkidc 网关** 的 Seedance 系列视频生成模型驱动。

kkidc 是火山 Seedance 的二次封装网关，接口结构与火山原生（`seedance_volcengine_v1`）**完全不同**：

| 维度 | 火山原生（seedance_volcengine_v1） | kkidc 网关（seedance_kkidc_v1） |
|------|-----------------------------------|-------------------------------|
| Base URL | `https://ark.cn-beijing.volces.com` | `https://ai-api.kkidc.com/v1` |
| 创建任务 | `POST /api/v3/contents/generations/tasks` | `POST /video/generations` |
| 查询任务 | `GET /api/v3/contents/generations/tasks/{id}` | `GET /video/generations/{task_id}` |
| 请求体 | `content[]` 数组 + 顶层参数 | 扁平 `prompt` + `metadata{}` |
| 响应体 | `{id, status, content:{video_url}}` | 三段式 `{code, message, data:{task_id, status, data:{...}}}` |

> 因此 kkidc 驱动**独立实现**，不能继承火山版驱动复用。

## 架构定位

kkidc 作为现有 4 个 Seedance 任务的**备选实现**，与火山国内版/海外版并列：

- 复用 TaskTypeId（21/22/23/31）、DriverKey、算力配置（power_modifiers），无需 DB 迁移
- 用户可在前端切换供应商；admin 可在后台禁用/排序（sort_order=10900~10930，默认排在海外版之后）
- 当 `kkidc.api_key` 未配置时，该实现自动从可用列表中排除（`required_config_keys` 检查）

## 支持的模型

| Task ID | kkidc 模型名 | 实现类 | DriverImplementation | ID |
|---------|-------------|--------|---------------------|-----|
| 22 | seed-2-fast | `Seedance20FastKkidcV1Driver` | `seedance_2_0_fast_kkidc_v1` | 59 |
| 23 | seed-2 | `Seedance20KkidcV1Driver` | `seedance_2_0_kkidc_v1` | 60 |
| 31 | seed-2-mini | `Seedance20MiniKkidcV1Driver` | `seedance_2_0_mini_kkidc_v1` | 61 |

> kkidc 网关使用自有的模型别名（`seed-2` / `seed-2-fast` / `seed-2-mini`），**非火山原生模型名**（`doubao-seedance-*-26xxxx`）。1.5 Pro 暂不对接。

## 配置项

在 admin 后台「系统设置 → 供应商 → video 分类 → kkidc」卡片配置：

| 配置键 | 说明 | quick_config |
|--------|------|:------------:|
| `kkidc.api_key` | kkidc 网关 API Key（必填，敏感） | ✅ |
| `kkidc.base_url` | API 基础 URL，默认 `https://ai-api.kkidc.com/v1` | ✅ |

## 接口规格

### 创建任务 `POST /video/generations`

请求体为扁平结构，按输入模式分支：

**文生视频**（无图片/音视频输入）：
```json
{
  "model": "doubao-seedance-2-0-260128",
  "prompt": "...",
  "metadata": {"generate_audio": true, "ratio": "16:9", "duration": 5, "watermark": false}
}
```

**首帧图生视频**（仅 1 张图，顶层 `image` 字段）：
```json
{
  "model": "...", "prompt": "...",
  "image": "https://cdn.../first.jpg",
  "metadata": {...}
}
```

**首尾帧图生视频**（2 张图，metadata 内嵌）：
```json
{
  "model": "...", "prompt": "...",
  "metadata": {"first_frame_image": "...", "last_frame_image": "...", ...}
}
```

**多参考图模式**：
```json
{
  "model": "...", "prompt": "...",
  "metadata": {
    "reference_images": ["url1", "url2"],
    "reference_videos": ["url1"],
    "reference_audios": ["url1"],
    "resolution": "720p",
    ...
  }
}
```

**成功响应**（HTTP 200）：
```json
{"code": "success", "message": "", "data": {"task_id": "cgt-20260227150701-bwgfp"}}
```

**错误响应**（HTTP 400/429）：
```json
{"error": {"message": "...", "type": "...", "param": "...", "code": "..."}}
```

### 查询任务 `GET /video/generations/{task_id}`

**成功响应**（三段式，data 内嵌 data）：
```json
{
  "code": "success",
  "data": {
    "task_id": "cgt-...",
    "status": "SUCCESS",
    "fail_reason": "...",
    "progress": "100%",
    "data": {
      "status": "succeeded",
      "content": {"video_url": "https://...mp4"}
    }
  }
}
```

### 状态映射

| kkidc 外层（大写） | 上游 data.data.status（小写） | 内部状态 | 处理 |
|-------------------|-----------------------------|---------|------|
| `SUCCESS` | `succeeded` | SUCCESS | 取 `data.data.content.video_url` |
| `FAILURE` | `failed` / `expired` | FAILED | 取 `fail_reason` 作错误信息 |
| `QUEUED` / `NOT_START` / `SUBMITTED` | `queued` | RUNNING | 处理中 |
| `IN_PROGRESS` | `running` | RUNNING | 处理中 |
| `UNKNOWN` | - | RUNNING | 未知，保守按处理中 |

> **fail_reason 容错**：kkidc 文档示例中成功响应的 `fail_reason` 曾误填为视频 URL，驱动做了过滤 —— 若 `fail_reason` 以 `http(s)://` 开头则视为异常，回退为"任务失败"。

## 错误处理策略

| 场景 | 处理 | Sentry |
|------|------|:------:|
| HTTP 400 内容审核错误 | 提取 `error.message`，走 `format_user_facing_moderation_error` 生成中文友好文案，`error_type:USER, retry:false` | ❌ |
| HTTP 400 参数错误 | `error_type:USER, retry:false` | ❌ |
| HTTP 429 限流 | 返回"上游限流，请稍后重试"，`error_type:USER, retry:true`（查询时保持 RUNNING 等下次轮询） | ❌ |
| 网络错误 / 超时 | `error_type:USER, retry:true` | ❌ |
| 响应格式异常 | `error_type:SYSTEM` | ✅ |

> **关键实现点**：基类 `_request` 在 HTTP 4xx/5xx 时调用 `raise_for_status()` 抛 `HTTPError` 并丢弃响应体。kkidc 驱动在 `submit_task`/`check_status` 中捕获 `HTTPError`，通过 `_extract_http_error_body()` 从 `e.response.json()` 重新提取错误体，从而把结构化错误透传给用户。

## 特性

- **文生视频**：无图片/音视频输入时自动启用（与火山版判定逻辑一致）
- **异步接口**：提交后返回 task_id，轮询 `check_status` 获取结果
- **多帧支持**：首帧（顶层 `image`）/ 首尾帧（metadata 内嵌）
- **多参考图**：`metadata.reference_images` 列表
- **参考音视频**：`metadata.reference_videos` / `metadata.reference_audios`（提交前上传 CDN）
- **face_mask**：复用 image_face_mask / face_mask pipeline step，避免审核不通过
