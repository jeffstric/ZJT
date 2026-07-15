# 故事板媒体导出

## 概述

支持两种导出，产物均上传图床（CDN），前端用 `download_url` 下载，不占用业务机带宽。对齐 `GET /api/export-world` 的交付方式。

| 方式 | 接口 | 交付 |
|------|------|------|
| 素材包 | `POST /api/storyboard/{id}/export-all-scenes` | 同步：打包 zip → CDN → `{download_url,filename}` |
| 完整视频 | `POST /api/storyboard/{id}/export-full-video` | 异步：`job_id` → 轮询 `GET /api/storyboard/export-job/{job_id}` → CDN |

权限：`storyboard:export`。

## 命名规则（素材包）

按 `sort_order` 1-based 序号 `i`：

- 有选中视频（`selected_video_id`）：`分镜{i}.mp4`（**不再写分镜图**）
- 无选中视频、有首帧：`分镜{i}.png|jpg|…`
- 第 j 条选中配音：`分镜{i}_{j}.wav`
- 另含 `manifest.json`

## 画面选择规则（素材包 + 完整视频共用）

与时间轴预览一致：**已选视频则必须用视频**，不能用分镜首帧图顶替。

1. 若 `selected_video_id` 有值，或 JOIN/`list` 已解析出 `video_url` → 按 **视频** 导出  
2. 视频 URL 解析顺序：`storyboard_scene_asset.result_url` → 关联 `ai_tools.result_url` 兜底  
   （生成完成后结果常只写在 `ai_tools`，asset 表可能为空）  
3. **有选中视频但 URL 仍解析失败**：`visual_type=none`，manifest 记 `video_missing`；**禁止**回退 `first_frame_url`  
4. **无选中视频**时，才用首帧图定格；下载/转码失败同样不改成另一种媒体  

## 完整视频合成规则

与时间轴预览一致（`storyboard_timeline_playback.md`）：

- 镜时长 = `scene.duration`（无效则 2s）
- 画面：按上节规则选视频 / 图 / 黑场（视频默认静音，见下「声音同出」例外）
- 视频短于 span 定格补满，长于则截断
- 配音串行，总长相对 span 截断/静音垫
- 镜间直接 concat

### 声音同出（audio_embedded）

`storyboard_scene.audio_embedded`（TINYINT，中文「声音同出」）控制单镜音轨来源：

- **关闭（默认，普通分镜）**：视频画面用 `-an` 丢弃原音轨，再混入本镜 TTS 配音（`_build_scene_audio` + `_mux_segment`）；无配音则补静音轨，保证整片音轨连续。
- **开启（数字人分镜默认）**：选中视频已内嵌对话声音（如 LTX2.3 口型产物），导出时**保留视频原音轨**、**跳过 TTS 混音**；音轨按 span 截断/静音补齐。

| 场景 | audio_embedded | 画面音轨 | TTS 配音 | 说明 |
|------|----------------|----------|----------|------|
| 普通视频分镜 | 0（默认） | 丢弃 | 混入 | 默认行为，TTS 为唯一音源 |
| 数字人分镜 | 1（默认） | 保留 | 跳过 | LTX2.3 产物已含口型音轨，避免重复混音 |
| 普通分镜手动开启 | 1 | 保留 | 跳过 | 适用于视频自带成片音轨、不希望再混 TTS 的场景 |

- 字幕不受影响：`audio_embedded` 只控制音轨，字幕仍按对白 `text` 时间轴生成 ASS 硬烧。
- 素材包导出（方式1）不受影响：素材包本就是视频与配音 wav 分开打包。
- 前端：分镜面板「声音同出」开关，切换后即时持久化（`PUT /scene/{id}` 仅传 `audio_embedded`）。

### 字幕硬烧（整片）

- 模块：`services/storyboard_subtitle.py`（独立于导出编排）
- Body：`include_subtitles`（默认 `true`）；前端导出弹框可取消勾选
- 时间轴：与有选中配音的对白串行一致；`text` + `audio duration`（库字段或 ffprobe）
- 版式：底部居中，最多 **3 行**，左右约 86% 宽，不占满屏
- 超长：折行后按 3 行分页，在对白时间窗内 **字数加权轮播**；时长不够则末页 `…`
- 技术：生成 ASS → ffmpeg `subtitles=` 硬烧（workdir 相对路径，兼容 Windows）

## 实现

- `services/storyboard_export_service.py`：清单、打包、ffmpeg 合成、job 状态、调用字幕模块
- `services/storyboard_subtitle.py`：折行 / 分页 / ASS / 滤镜参数
- `api/storyboard.py`：导出路由
- `config/constant.py`：`StoryboardTimeouts` / `StoryboardExportConstants` / `StoryboardSubtitleConstants`
- 前端：`events.js` 导出回调 + CDN 链接点击下载

## 依赖

- 本机 `bin.ffmpeg` / `bin.ffprobe`
- `file_storage.qiniu` 配置完整（与世界导出相同）
