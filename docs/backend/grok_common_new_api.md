# Grok 通用聚合站点驱动对接新视频生成接口

## 背景

`task/visual_drivers/grok_common_v1_driver.py`（yunwu.ai 聚合站点驱动，对应 `site_0` ~ `site_5`）原先对接的是旧接口：

- 创建：`POST {base_url}/v1/video/create`，model=`grok-video-3-10s`，字段 `images`(字符串数组) / `size` / `aspect_ratio`
- 旧接口仅支持扁平的图片列表，字段与能力与新平台不匹配。

现切换到 yunwu.ai 新接口 `POST /v1/videos/generations`，model=`grok-imagine-video`，并支持两种图片输入语义：**首帧模式**（`image`）与**多参模式**（`reference_images`）。

## 新接口规格

```
POST {base_url}/v1/videos/generations
Authorization: Bearer {api_key}
Content-Type: application/json
```

```json
{
    "model": "grok-imagine-video",
    "prompt": "提示词",
    "resolution": "720p",
    "aspect_ratio": "9:16",
    "duration": 10,
    "image": { "url": "https://..." },
    "reference_images": [ { "url": "https://..." }, { "url": "data:image/jpeg;base64,/9j/4AAQ..." } ]
}
```

约束：
- `model` / `prompt` / `resolution` / `aspect_ratio` / `duration` 全部必填。
- `image` 与 `reference_images` **互斥**，不能同时使用。
- `resolution` 仅支持 `480p` / `720p`；`aspect_ratio` 仅支持 `1:1` / `16:9` / `9:16`；`duration` 范围 `[1, 15]`。
- **图片源（`url` 字段）支持两种等价形式**：
  - 公网 HTTPS URL（直接透传）；
  - base64 data URI：`data:image/jpeg;base64,...`。
  底层 x.ai 不支持 `http://`（实测返回 `invalid_argument: Fetching images over plain http:// is not supported.`），因此非公网 HTTPS 源（本地路径/局域网/本机服务 URL/外网 http）在驱动内统一压缩转 base64 data URI 后再发送，不再依赖图床。

### 创建响应

创建成功返回任务标识 `request_id`（**不是 `id`**）：
```json
{ "request_id": "86856ed7-b0ce-9cc7-b170-792c38e1321c" }
```
`submit_task` 用 `result.get("id") or result.get("request_id")` 提取 project_id（兼容两种字段），`_validate_submit_response` 同样接受二者之一。

### 查询接口

```
GET {base_url}/v1/videos/{request_id}
Authorization: Bearer {api_key}
```

返回格式**分阶段**（实测）：
- 早期（刚提交/排队中）：仅 `{"request_id": "..."}`，尚无 `status`
- 处理中：`{"status": "processing", ...}`
- 完成（**status 为 `done`，非 `completed`**）：
```json
{
    "model": "grok-imagine-video",
    "usage": { "cost_in_usd_ticks": 4260000000 },
    "video": { "url": "https://vidgen.x.ai/.../xxx.mp4", "duration": 6, "respect_moderation": true },
    "status": "done",
    "progress": 100
}
```
- 失败：`{"id": "...", "status": "failed", "error": {"code": "...", "message": "..."}}`

`_validate_status_response` 只校验是否为合法 dict（早期无 `status` 也通过，不再误判为格式错误）；`check_status` 按 `status` 解析：`done`/`completed`/`succeeded`/`success`（及大写）经 `_extract_video_url` 提取 `video.url` 返回 SUCCESS（**实测成功态为 `done`，视频 url 在顶层 `video.url`**）；`failed`/`error` 提取 `error.message` 返回 FAILED；无 `status` 或 `processing` 兜底为 RUNNING。

## 字段映射（新接口 → 数据来源）

| 新接口字段 | 来源 |
|---|---|
| `model` | 类常量 `MODEL_NAME = "grok-imagine-video"` |
| `prompt` | `ai_tool.prompt` |
| `resolution` | 类常量 `RESOLUTION = "720p"`（AITool 无该字段，固定 720p） |
| `aspect_ratio` | `ai_tool.ratio`，经 `_map_aspect_ratio` 兜底映射到 `1:1`/`16:9`/`9:16` |
| `duration` | `ai_tool.duration`；非 `6/10/15` 档位回退默认 10，并 `max(1,min(15))` 边界防御 |
| `image` | 首帧模式 → `{"url": ...}`（单张，忽略尾帧）；url 为公网 HTTPS 透传或 base64 data URI |
| `reference_images` | 多参模式 → `[{"url": ...}, ...]`（最多 7 张）；url 同上，逐张独立处理 |

## 图片模式语义与互斥规则

基于基类 `get_all_images_by_mode` 解析出的 `ImageMode` 分支处理：

| 模式 | 新接口字段 | 说明 |
|---|---|---|
| `FIRST_LAST_FRAME`（首帧模式） | `image` | 取首帧填入 `image`；新接口 `image` 仅单张，**忽略尾帧**并打 warning（与任务配置 `supports_last_frame=False` 一致） |
| `MULTI_REFERENCE`（多参模式） | `reference_images` | 参考图填入 `reference_images`，超过 `MAX_REFERENCE_IMAGES`(7) 张截断 |
| `FIRST_LAST_WITH_REF` | `image` 优先 | `image` 与 `reference_images` 互斥；有首帧时优先 `image` 并忽略参考图，无首帧时回退多参 |

### 图片源处理（`_build_image_payload` / `_source_to_data_uri`）

每张图片源经 `_build_image_payload(source)` 转为 `{"url": ...}`：
- **已是 data URI**（`data:` 开头）→ 直接透传；
- **公网 HTTPS**（`https://` 且非局域网/私有地址）→ 直接透传；
- **其余源**（本地文件路径 / 本机服务 URL / 外网 `http://` / 其它协议）→ 压缩转 base64 data URI：
  - 本地文件路径 → `compress_local_image_to_base64`（`utils/image_compressor.py`）；
  - URL → 优先用 `extract_local_path_from_url`（`utils/media_mapping_util.py`）按 `/upload/` 前缀映射为本服务本地文件（与域名无关，**避免回环下载自身服务器**，如 `http://zjt_dev.perseids.cn/upload/...` → `<project_root>/upload/...`）；映射命中且文件存在则直接压缩；
  - 外网 URL（非 `/upload/`）或本地映射未命中 → `url_to_base64`（httpx 同步下载 + 压缩）兜底。
- 压缩策略：**仅按体积温和压缩**，`_IMAGE_MAX_MB=2.0`、`_IMAGE_MAX_PIXELS=0`。
  - ≤2MB 的图**原样发送**（含 PNG，不重编码，保留参考图细节/人物）；
  - >2MB 的图才压缩（`compress_image_to_limit`：JPEG 质量 95→60 自适应，仅当质量压不下去时才缩尺寸）。
  - ⚠️ **`_IMAGE_MAX_PIXELS` 必须保持 0**。`compress_local_image_to_base64` 的 `max_pixels>0` 分支是为 **LLM 视觉理解**（日志 `[VL]`）省 token 设计的——会强制缩到 max_pixels + JPEG q85 重编码，对视频参考图过度有损（曾把 1.3MB 图压成 45KB、导致人物丢失）。视频参考图只做体积压缩，不做 LLM 式强制缩放。

错误语义：首帧（`image`，单张必需）转换失败 → 抛 `RuntimeError`（由 `submit_task` 的 `except` 兜成 SYSTEM 错误，不发坏数据）；参考图单张失败 → 丢弃该张继续，全部失败才抛错。转换失败的真实 `err` 会写入日志。

> 该方案替代了原先 `ensure_public_urls(force_upload=True)` 强制重传图床的逻辑——grok 接口本身支持 base64 data URI，故不再依赖图床。全程纯同步，不触碰事件循环（`submit_task` 在运行中的事件循环里被同步内联调用）。

### 日志脱敏

`_request` 经基类 `_mask_sensitive_payload` 把完整 payload 写入 `logs/api_requests.log`。base64 data URI 可达数 MB，多图请求会写出超长日志行；基类 `_mask_data_uri` 会对以 `data:` 开头且超长（>200 字符）的字符串值截断，真实 URL 不受影响。

## payload 改动前后对比

改动前（旧接口）：
```json
{
    "model": "grok-video-3-10s",
    "prompt": "...",
    "aspect_ratio": "9:16",
    "size": "720P",
    "images": ["https://..."]
}
```

改动后（新接口，首帧模式）：
```json
{
    "model": "grok-imagine-video",
    "prompt": "...",
    "resolution": "720p",
    "aspect_ratio": "9:16",
    "duration": 10,
    "image": { "url": "https://..." }
}
```

改动后（新接口，多参模式，混合 HTTPS 透传 + base64 data URI）：
```json
{
    "model": "grok-imagine-video",
    "prompt": "...",
    "resolution": "720p",
    "aspect_ratio": "9:16",
    "duration": 10,
    "reference_images": [
        { "url": "https://..." },
        { "url": "data:image/jpeg;base64,/9j/4AAQ..." }
    ]
}
```

## 关键决策

1. **model 版本**：默认 `grok-imagine-video`（稳定版）；`grok-imagine-video-1.5-preview`（预览版）暂不接入，后续如需可通过 `extra_config` 扩展。
2. **resolution 固定 720p**：AITool 无 resolution 字段，driver 内固定 `RESOLUTION = "720p"`，与旧 `size='720P'` 行为一致。
3. **aspect_ratio 收紧**：新接口仅支持 `1:1`/`16:9`/`9:16`，因此任务配置 `supported_ratios` 同步收紧为这三项；driver 内 `_map_aspect_ratio` 仍对 `2:3/3:4`（→`9:16`）、`3:2/4:3`（→`16:9`）等做兜底映射，避免前端传非常规比例时接口直接报错。
4. **时长扩展为 6/10/15 秒**：任务配置 `supported_durations` 由 `[10]` 扩展为 `[6, 10, 15]`；driver 对非档位值回退默认 10 并做 `[1,15]` 边界防御。
5. **多参模式开放**：任务配置 `supported_image_modes` 由仅 `FIRST_LAST_FRAME` 扩展为 `[FIRST_LAST_FRAME, MULTI_REFERENCE]`，前端方可选择多参模式；`max_multi_ref_images=7`。
6. **算力按时长差异化**：6 个 common 站点的 `default_computing_power` 由固定 `8` 改为按时长映射。
   - `grok_common_site0_v1`（ZJTapi / yw.perseids.cn）：按供应商实际成本（6秒 1.266 / 10秒 2.118 / 15秒 3.156 元）+ 不亏本（1 算力 = 0.04 元，向上取整到 5）配置为 `{6: 35, 10: 55, 15: 80}`。
   - `site1`~`site5`：暂用统一兜底 `{6: 6, 10: 8, 15: 12}`，待各供应商提供实际成本后再各自精算（或由供应商在数据库 `ImplementationPowerModel` 覆盖）。

## 影响范围

- `task/visual_drivers/grok_common_v1_driver.py`
  - 类常量更新（`MODEL_NAME` 改名、新增 `RESOLUTION`/`DEFAULT_DURATION`/`MAX_REFERENCE_IMAGES`）
  - 新增 `_map_aspect_ratio` 辅助方法
  - 重写 `build_create_request`（对接 `/v1/videos/generations`，支持首帧/多参）
  - 创建/查询响应适配：`_validate_submit_response`/`submit_task` 接受 `request_id`；`build_check_query` 改为 `GET /v1/videos/{request_id}`；`check_status` 按新返回格式（`status` + `error`）解析
- `config/unified_config.py`
  - grok 任务（`id=27, key='grok_image_to_video'`）：`supported_ratios` 收紧、`supported_image_modes` 加多参、`max_multi_ref_images=7`、`supported_durations=[6,10,15]`
  - `grok_common_site0`~`site5` 实现方：`default_computing_power` 按时长差异化
- `docs/backend/grok_common_new_api.md`（本文档）

## 待跟进

- **图片源 http 问题（已解决）**：实测发现新接口（底层 x.ai）拒绝 `http://` 图片源，返回 `Fetching images over plain http:// is not supported.`。原先通过 `ensure_public_urls(force_upload=True)` 强制重传图床来规避；现已改为 base64 data URI 方案（见上文「图片源处理」）：公网 HTTPS 透传，其余源（含 `http://zjt_dev.perseids.cn` 这类仅 http 的源）统一压缩转 base64 data URI 后发送，彻底不再依赖图床。
- **base64 data URI 落在 `url` 字段需实测确认**：本方案将 data URI 放在与 HTTPS URL 相同的 `url` 字段（grok 接口文档表述「公网 HTTPS URL 或 base64 data URI」）。上线前建议用单图 curl 实测一次接口是否接受该形态；若实际需要独立字段（如 `b64_json`），再调整 `_build_image_payload` 的返回结构。
- **grok_duomi 时长兼容性（已解决）**：grok 任务 `supported_durations=[6,10,15]` 对所有实现方生效；原先 `grok_duomi_v1_driver.build_create_request` 写死 `duration=self.DURATION(10)`，忽略用户传入时长。已修复为优先取 `ai_tool.duration`，按 6/10/15 档位校验（缺失/非法/非档位回退默认 10），与 `grok_common` 驱动一致。
