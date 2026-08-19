# Grok huimengi（慧梦）网关驱动

## 概述

`grok_huimengi_v1` 是慧梦（huimengi）网关下 Grok 视频模型的实现方，与多米
（`grok_duomi_v1`）和聚合站点（`grok_common_site0~5`）并列，作为 Grok 图生视频任务
（TaskTypeId=27）的第 8 个备选实现方。网关侧模型名为 `grok-video-channel`。

驱动文件 `task/visual_drivers/grok_huimengi_v1_driver.py` 中的
`GrokHuimengiV1Driver` **直接继承 `SeedanceHuimengiV1Driver`**：
huimengi 网关的提交/查询端点、鉴权、状态机、错误处理（429 限流、内容审核友好文案、
HTTP 错误体提取、Sentry 报警）完全同构，全部复用基类；仅重写
`build_create_request` 以适配 grok-video-channel 的参数集。

## 架构定位

- **任务**：Grok 图生视频（`TaskTypeId.GROK_IMAGE_TO_VIDEO` = 27，
  `short_key='grok'`），支持文生 + 图生，比例 9:16 / 16:9 / 1:1，时长档位 6 / 10 / 15
- **实现方**：`grok_huimengi_v1`，`DriverImplementationId = 70`，`sort_order=4610.0`
  （排在 grok_common_site5 之后，处于 Grok 实现方重试链末位）
- **配置键**：复用 `huimengi.api_key` / `huimengi.base_url`（与 Seedance 共用）
- **无需数据库迁移**：仅是现有 Grok 任务的新实现方；算力可经 `implementation_power`
  表在管理后台热调
- 当 `huimengi.api_key` 未配置时，实现方自动隐藏（由 `required_config_keys` 控制）
- 前端无需改动：模型参数由 `/api/system/task-configs` 动态下发，admin「实现方管理」
  页经 `config/constant.py` 的 `DRIVER_IMPLEMENTATION_MAPPING` 自动显示

## 算力定价

成本 0.05 元/秒，1 算力 = 0.04 元（`AdminBillingConstants.POWER_YUAN`），保持 ≥5% 盈利：

```
算力 = ceil(时长(秒) × 0.05 × 1.05 ÷ 0.04)
```

| 时长 | 成本 | 成本×1.05 | 算力（向上取整） | 实收 | 实际利润率 |
|------|------|-----------|------------------|------|-----------|
| 6s   | 0.30 元 | 0.315 元 | 8  | 0.32 元 | 6.25% |
| 10s  | 0.50 元 | 0.525 元 | 14 | 0.56 元 | 10.7% |
| 15s  | 0.75 元 | 0.788 元 | 20 | 0.80 元 | 6.25% |

`default_computing_power = {6: 8, 10: 14, 15: 20}`。

## 接口规格

### 鉴权

```
Authorization: Bearer hm-xxxxxxxxxxxxxxxx
```

### 创建任务

**POST** `{huimengi.base_url}/api/v1/tasks`

请求体结构（扁平 `{model, params}`，与 Seedance 系列一致）：

```json
{
  "model": "grok-video-channel",
  "params": {
    "prompt": "一只猫在海滩上漫步",
    "ratio": "16:9",
    "duration": 6,
    "resolution": "720p"
  }
}
```

提交成功响应：

```json
{
  "task_id": "a820e1b8-fb15-4ec9-a13c-bdd1d4eb6679",
  "status": "pending"
}
```

`webhook_url` 为网关可选字段，本驱动不下发（沿用提交 + 轮询模式）。

### 查询任务

**GET** `{huimengi.base_url}/api/v1/tasks/{task_id}`

成功 / 失败响应结构与 Seedance 系列一致（`status: completed/failed`，
视频地址 `result.video_url`，失败原因 `error_message`），状态映射复用基类：

| huimengi status | 内部状态 | 处理 |
|-----------------|----------|------|
| `pending` | RUNNING | 等待生成 |
| `processing` | RUNNING | 生成中 |
| `completed` | SUCCESS | 取 `result.video_url` |
| `failed` | FAILED | 取 `error_message` |

### params 字段映射（与 Seedance 系列的差异）

| 字段 | 类型 | 必填 | 驱动处理 |
|------|------|------|---------|
| `prompt` | string | 是 | **文生/图生均必填**，上游限制 5-20000 字符；<5 字符返回 USER 错误，>20000 截断 |
| `ratio` | string | 否 | 网关可选 2:3 / 3:2 / 1:1 / 16:9 / 9:16（默认 16:9）；驱动始终显式下发，缺省 9:16（任务默认） |
| `duration` | integer | 否 | 网关范围 6-15（默认 6）；驱动按任务档位 6/10/15 校验，非法回退 10，并 clamp [6,15] |
| `resolution` | string | 否 | 网关可选 720p / 480p（默认 720p）；驱动固定下发 720p（前端 Grok 无分辨率选择） |
| `image_url` | string | 否 | 单张首帧参考图（公网 URL），传入后走图生视频 |
| `reference_images` | array | 否 | 参考图公网 URL 列表，最多 7 张 |

**不支持**（相对 Seedance 系列裁剪）：尾帧（`first/last_frame_image`）、参考音视频
（`reference_videos` / `reference_audios`）、`generate_audio`、`human_review`——
grok-video-channel 网关未开放这些字段，驱动不透传。

### 图片模式处理

`image_url` 与 `reference_images` 互斥，由 `get_all_images_by_mode` 解析后按下表决定：

| 模式 | 处理 |
|------|------|
| 无任何图片（文生视频） | 仅 prompt + 控制字段 |
| `first_last_frame` | 首帧 → `params.image_url`；**尾帧忽略**（任务 `supports_last_frame=False`，与 grok_common 行为一致） |
| `multi_reference` | → `params.reference_images[]`，上限 7 张，超出截断 |
| `first_last_with_ref` | 优先首帧 → `image_url`，参考图忽略；无首帧时降级用参考图 |
| 首帧模式缺首帧但有参考图 | 降级用参考图列表 |
| 未知模式 | 按可用图片降级处理，避免静默丢失图片输入 |

图片统一经 `compress_and_upload_image_sync`（≤10MB，本地图走压缩）上传自有 CDN 后
以公网 URL 下发：首帧失败返回 USER 错误不重试；参考图单张失败跳过，**全部失败返回
USER 错误**（避免静默退化为文生视频）。

## 错误处理策略

复用基类 `SeedanceHuimengiV1Driver` 的完整策略：

| 场景 | 处理 | retry |
|------|------|-------|
| HTTP 400 内容审核 | `format_user_facing_moderation_error` 友好文案 | False |
| HTTP 400 参数错误 | 返回 API 错误文案 | False |
| HTTP 429 限流 | "上游限流，请稍后重试"（查询时保持 RUNNING） | True |
| 网络错误（Connection/Timeout） | "网络连接异常，请稍后重试"（查询时保持 RUNNING） | True |
| 响应格式异常 | Sentry 报警 + "服务异常，请联系技术支持" | False |
| prompt 为空 / <5 字符 | USER 错误提示 | False |
| 图片上传失败 | USER 错误提示 | False |

## 单元测试

`tests/drivers/test_grok_huimengi_v1_driver.py`（23 个用例），覆盖：

- 初始化（driver_type=27、model、impl_name、配置加载）
- build_create_request：文生 / 首帧（尾帧忽略）/ 多参考（7 张上限、全失败报错）/
  prompt 三段校验 / duration 回退与透传 / ratio 优先级 / Seedance 专属字段不透传 /
  不含 webhook_url
- submit_task：成功提取 task_id、429 重试、网络错误重试、构建期 USER 错误透传
- check_status：四态映射

```bash
pytest tests/drivers/test_grok_huimengi_v1_driver.py -v
```
