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

- **文生视频**：支持纯文本生成视频（无任何图片/音视频输入时自动启用，content 仅含 `text`）
- **异步接口**：提交任务后返回 `project_id`，通过轮询 `check_status` 获取结果
- **多帧支持**：支持首帧（first_frame）、尾帧（last_frame）
- **多参考图**：支持 `multi_reference` 模式下多张参考图（role: reference_image）
- **参考视频**：支持传入参考视频（role: reference_video）
- **参考音频**：支持传入参考音频（role: reference_audio）
- **图片压缩上传**：本地图片自动压缩后上传至 CDN
- **参考视频规范化**：提交前会将 WebM/MKV 参考视频转为 H.264/AAC MP4，避免浏览器 `MediaRecorder` 产物缺少 duration 元数据导致火山输入适配器失败
- **图片人脸网格预处理**：Seedance 2.0 系列图片输入使用自适应红色矩形网格降低人脸敏感度

## Seedance 2.0 人脸输入预处理

启用 `pipeline.seedance_face_mask_enabled` 后，Seedance 2.0 系列会在正式提交前处理输入图片和视频：

- **图片输入**：RunningHub 识别人脸并返回黑块结果后，本地从原图和黑块图中恢复人脸矩形框，再在原图上绘制红色网格。网格内部保留原始图片内容，不填充色块。
- **多脸图片**：每张检测到的人脸分别绘制独立矩形网格。
- **网格密度**：按人脸框短边像素使用 3×3、5×5、8×8、10×10 四档；小脸自动减少行列数。
- **网格线宽**：按完全包含吞噬后的最终人脸矩形数量统一分档；1–5 个使用 1px、6–10 个使用 2px、11 个及以上使用 3px。被吞噬的小矩形不参与计数。
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
