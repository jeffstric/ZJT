# Seedance 火山引擎供应商驱动 (seedance_volcengine_v1)

## 概述

`seedance_volcengine_v1_driver.py` 实现了调用火山引擎 Seedance 系列视频生成模型的驱动，支持**文生视频**与**图生视频**，使用异步 API（创建任务后轮询状态）。

## 支持的模型

| Task ID | 模型名称 | 实现类 | 支持的图片模式 | 支持参考音频/视频 |
|---------|---------|--------|---------------|-----------------|
| 21 | doubao-seedance-1-5-pro-251215 | `Seedance15ProVolcengineV1Driver` | first_last_frame | 支持 |
| 22 | doubao-seedance-2-0-fast-260128 | `Seedance20FastVolcengineV1Driver` | first_last_frame, multi_reference | 支持 |
| 23 | doubao-seedance-2-0-260128 | `Seedance20VolcengineV1Driver` | first_last_frame, multi_reference | 支持 |
| 31 | doubao-seedance-2-0-mini-260615 | `Seedance20MiniVolcengineV1Driver` | first_last_frame, multi_reference | 支持 |
| 36 | doubao-seedance-2-5-260628 | `Seedance25VolcengineV1Driver` | first_last_frame, multi_reference | 支持（含纯音频） |

> **Seedance 2.0 Mini**：价格为 Seedance 2.0 的一半，功能与 Seedance 2.0 一致。
>
> **Seedance 2.5**：接口协议与 2.0 系列完全一致（content 数组结构、role 取值、状态轮询），仅 `model` 名不同。额外支持：纯音频输入（无图无视频）、最多 30 张参考图 / 10 个参考视频 / 10 段参考音频、视频时长 [4,30]s。支持分辨率 480P / 720P / 1080P（不支持 4K），1080P 算力为 720P 的 1.78 倍。火山国内版实现方 `seedance_2_5_volcengine_v1` 的数字 ID 为 **68**，huimengi 网关实现方 `seedance_2_5_huimengi_v1` 为 **69**，均不可复用 MiniMax H3 参考生视频的 67。

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

### Seedance 2.5 算力

2.5 沿用与 2.0 相同的口径（720p、输入含视频且输入 15s 的最高成本），基于官方刊例价（单价 42 元/百万 token）推导：

`tokens = 38880 × 输出秒 + 21600 × (15 − 4)`，`算力 = ceil(tokens × 42 ÷ 40000)`

| 输出时长 | seedance-2.5 | | 输出时长 | seedance-2.5 |
|---------:|-------------:|---|---------:|-------------:|
| 5 秒 | 454 | | 18 秒 | 985 |
| 6 秒 | 495 | | 19 秒 | 1026 |
| 7 秒 | 536 | | 20 秒 | 1066 |
| 8 秒 | 577 | | 21 秒 | 1107 |
| 9 秒 | 617 | | 22 秒 | 1148 |
| 10 秒 | 658 | | 23 秒 | 1189 |
| 11 秒 | 699 | | 24 秒 | 1230 |
| 12 秒 | 740 | | 25 秒 | 1271 |
| 13 秒 | 781 | | 26 秒 | 1311 |
| 14 秒 | 822 | | 27 秒 | 1352 |
| 15 秒 | 862 | | 28 秒 | 1393 |
| 16 秒 | 903 | | 29 秒 | 1434 |
| 17 秒 | 944 | | 30 秒 | 1475 |

> 2.5 支持 480P / 720P / 1080P。480P 通过 `SEEDANCE_480P_PRICE_MULTIPLIER` 换算（与 2.0 共用）；1080P 通过 `SEEDANCE_2_5_1080P_PRICE_MULTIPLIER = 1.78` 换算。
>
> **视频编辑（2.5 + 参考视频）计费时长**：输出时长由参考视频决定（API 下发 `duration=-1`），计费「输出秒」取**参考视频总时长**（多视频求和 → 向上取整 → clamp 5–30，零头按 1 秒计），而非用户输入时长；探测失败回退用户输入。统一入口 `utils/computing_power.py::resolve_video_edit_billing_duration`，见下文「计费口径」说明。

## 特性

- **文生视频**：支持纯文本生成视频（无任何图片/音视频输入时自动启用，content 仅含 `text`）
- **异步接口**：提交任务后返回 `project_id`，通过轮询 `check_status` 获取结果
- **多帧支持**：支持首帧（first_frame）、尾帧（last_frame）
- **多参考图**：支持 `multi_reference` 模式下多张参考图（role: reference_image）
- **参考视频**：支持传入参考视频（role: reference_video）
- **参考音频**：支持传入参考音频（role: reference_audio）
- **纯音频输入**：无图片、无视频、仅参考音频时自动走多参考模式（详见下文「纯音频输入」），Seedance 2.0 系列与 2.5 均支持
- **图片压缩上传**：本地图片自动压缩后上传至 CDN
- **参考视频规范化**：提交前会将 WebM/MKV 参考视频转为 H.264/AAC MP4，避免浏览器 `MediaRecorder` 产物缺少 duration 元数据导致火山输入适配器失败
- **图片人脸网格预处理**：Seedance 2.0 系列图片输入使用自适应红色矩形网格降低人脸敏感度

## Seedance 2.0 人脸输入预处理

启用 `pipeline.seedance_face_mask_enabled` 后，Seedance 2.0 系列会在正式提交前处理输入图片和视频：

- **图片输入**：RunningHub 识别人脸并返回黑块结果后，本地从原图和黑块图中恢复人脸矩形框，再在原图上绘制红色网格。网格内部保留原始图片内容，不填充色块。
- **多脸图片**：每张检测到的人脸分别绘制独立矩形网格。
- **网格密度**：按人脸框短边像素使用 3×3、5×5、8×8、10×10 四档；小脸自动减少行列数。
- **网格线宽**：按完全包含吞噬后的最终人脸矩形数量统一分档；1–5 个使用 3px、6–10 个使用 4px、11 个及以上使用 5px。被吞噬的小矩形不参与计数。
- **包含去重**：完全位于更大人脸框内部的小矩形不再重复绘制；部分重叠和相邻人脸框保持独立。
- **安全回退**：原图下载、矩形提取或网格写入失败时继续使用 RunningHub 黑块图，不回退到未经处理的原图。
- **视频输入**：仍使用原有黑色遮罩处理，本次未修改。

图片网格算法由 `enterprise/services/face_mask/` 提供，主仓库只保留 Pipeline、RunningHub 驱动和兼容调用门面。商业版启动时通过 `enterprise.register()` 注册 Provider；社区版不会创建该处理步骤。

## 生成视频的人脸网格前缀自动裁剪

当 Seedance 图生视频任务启用了图片人脸网格预处理，并且 `image_face_mask` 流水线步骤已完成时，生成结果在落库为 `COMPLETED` 前会自动检查视频开头的红色网格。

视频网格检测与裁剪算法同样位于 `enterprise/services/face_mask/`，下载队列、同步任务和视觉任务继续调用主仓库稳定门面。

- 只扫描起始 `0.5` 秒，按 FFprobe 帧 PTS 找到最后一个网格帧，并从精确下一帧开始裁剪；
- 本地结果、下载缓存结果和下载队列异常 fallback 使用同一后处理服务，最终只持久化一次服务返回 URL；
- 图片结果、未命中 `image_face_mask`、不可映射的远程 fallback 或关闭功能开关时跳过并保留原 URL；
- 未检测到网格时不转码；探测、解码、裁剪、校验等普通异常均 fail-open，不会把已经生成成功的 Seedance 任务改为失败；
- 异步完成路径使用非阻塞实现；同步模型的裁剪只在任务工作进程执行，结果调度线程不会运行 FFmpeg。

具体检测、输出复用和跨平台单飞锁约束见商业版文档 `enterprise/doc/generated_video_face_grid_prefix_trim.md`。

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

文生视频（text-to-video）模式下 content 仅包含一个 `text` 元素，无需任何图片/音视频输入：

```json
{
  "model": "doubao-seedance-1-5-pro-251215",
  "content": [
    {"type": "text", "text": "视频描述提示词"}
  ],
  "duration": 5,
  "ratio": "9:16",
  "watermark": false
}
```

> 文生视频任务由文生视频接口 `/api/ai-app-run` 创建（不带 `image_mode`）。驱动在检测到无任何图片/音视频输入、且 `extra_config` 未声明 `image_mode` 时自动走文生视频分支；图生视频接口 `/api/ai-app-run-image` 因必带 `image_mode`，永远不会被误判。

> `ratio` 只在文生视频、多参考（multi_reference）模式下下发。首帧/首尾帧模式（含未知模式降级为首尾帧）输出比例跟随首帧图片，火山会拒绝显式 `ratio`（400 `InvalidParameter.TaskTypeConstraint`），驱动构建 payload 时自动省略该字段。
>
> **Seedance 2.5 参考视频（视频克隆/编辑）**：火山会按提示词把任务判成 video editing，此时 `ratio` 必须为 `adaptive`、`duration` 必须为 `-1`，输出画幅和时长跟随参考视频（参考视频须 4–30 秒）。驱动命中视频编辑判定时显式下发 `omni_reference_task_type: "edit"`（常量 `config/constant.py::OMNI_REFERENCE_TASK_TYPE_EDIT`）并自动改写 `ratio`/`duration`，接口提交时即提前校验参数限制，消除 auto 自动判定错型导致的异步报错（`InvalidParameter.TaskTypeConstraint` / `TaskTypeMismatch`）；普通文生/图生仍下发用户选择的比例和时长，且不下发 `omni_reference_task_type`。
>
> **计费口径（视频编辑）**：视频编辑任务的输出时长由参考视频决定，算力按**参考视频总时长**计，不再按用户输入时长。判定与解析的唯一入口为 `utils/computing_power.py::resolve_video_edit_billing_duration`（内部先调共享谓词 `is_video_edit_billing_task`，命中任务集合见 `config/constant.py::VIDEO_EDIT_BILLING_TASK_TYPES`，驱动层下发 edit 与计价层共用，禁止调用方自写条件）：ffprobe 探测参考视频总时长 → 向上取整到整数秒（不足 1 秒的零头按 1 秒计，含 1µs 浮点容差防整数秒误加）→ clamp 到任务 `supported_durations` 区间（2.5 为 5–30）；探测失败回退用户输入时长。扣费（`/api/ai-app-run-image`，探测经 `asyncio.to_thread` 包装）、`ai_tools.duration` 落库、企业工具估算（`enterprise/tools/video_tools.py`）、Agent 算力确认估算（`power_confirm.py`）均调用同一函数；`extra_config` 落库 `user_duration_seconds` 与 `billing_duration_source`（`reference_video`/`user_input`）供审计。WebM/MKV 缺容器 duration 元数据时（浏览器 MediaRecorder 录制产物）自动转码 MP4 后重探，避免计费静默回退用户输入时长（曾致 10s 视频只扣 5s 档算力）。退费不受影响：第一优先级按扣费流水原额退还（免疫供应商切换/价格热更新），兜底重算用 `ai_tools.duration`（与扣费同源）。

## 纯音频输入

Seedance 2.0 系列与 2.5 支持「无图片、无视频、仅参考音频」的全模态参考输入（2.5 还支持单独传入音频）。涉及三层配合：

0. **前端放行**（`/image-to-video` 页面）：多参考模式下，无图片但有参考音频/视频且模型 `supports_ref_audio_video=True` 时（`isPureMediaRef`），`canSubmit`/`handleSubmit` 允许 0 张图提交，不再弹「请先上传至少一张图片」。
1. **server.py 放行**（`/api/ai-app-run-image`）：当前端默认 `image_mode=first_last_frame` 且无图片、仅有音频/视频、模型 `supports_ref_audio_video=True` 时，自动改判为 `multi_reference` 放行，避免被「首尾帧需要至少1张图片」拦截。
2. **驱动兜底**（`build_create_request`）：检测到「有参考音频/视频、无任何图片、非文生视频」时，强制 `img_mode = multi_reference`，确保 `MULTI_REFERENCE` 分支下发 `reference_audio` / `reference_video`。覆盖 CLI、storyboard API 等不经过 server.py 重定向的入口。

纯音频 content 示例（content 仅含 text + reference_audio，无任何 image_url）：

```json
{
  "model": "doubao-seedance-2-5-260628",
  "content": [
    {"type": "text", "text": "用这段音频的节奏生成视频"},
    {"type": "audio_url", "audio_url": {"url": "参考音频URL"}, "role": "reference_audio"}
  ],
  "duration": 5,
  "ratio": "16:9",
  "generate_audio": true
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

> 文生视频模式下 content 只含 `text` 元素、无 role，不涉及上述任何图片/音视频角色。

## 参考音频/视频数据来源

参考音频和参考视频优先从 `ai_tool` 模型字段读取，向后兼容 `extra_config`：

1. **参考视频**：优先读取 `ai_tool.video_path`，备选 `extra_config.reference_video`
2. **参考音频**：优先读取 `ai_tool.audio_path`，备选 `extra_config.reference_audio`

### 参考视频规范化

多参考模式下，驱动会先调用 `prepare_seedance_reference_video_sync()` 处理参考视频：

- `.webm` / `.mkv`：下载或映射到本地后，用 ffmpeg 转为 `.mp4`（H.264 + AAC，`+faststart`），再上传 CDN。
- `.mp4` / `.mov` 等其他格式：保持原逻辑，直接上传或透传。
- 转码产生的临时文件会在 CDN 上传后清理。

这个步骤用于规避 Chrome `MediaRecorder` 生成的 WebM 常见问题：文件可播放，但容器 `format.duration` 和 `stream.duration` 为空，Seedance v2 输入适配器会报 `parse media duration: strconv.ParseFloat: parsing "": invalid syntax`。

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
