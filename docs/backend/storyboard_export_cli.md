# Storyboard Agent CLI 导出命令

通过 `storyboard-agent-cli` 或 `POST /api/storyboard/agent/commands/{command}` 调用以下三个导出命令，完成从生成到导出的全流程。

## 命令总览

| 命令 | 权限 | 用途 |
|------|------|------|
| `export-check` | `storyboard:export` | 导出前核查素材完整性 |
| `export-full-video` | `storyboard:export` | 合成整集 MP4 并上传 CDN |
| `export-package` | `storyboard:export` | 打包素材 zip 并上传 CDN |

## export-check

导出前检查所有分镜的素材完整性，返回缺失清单。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `storyboard_id` | int | 是 | 故事板 ID |
| `user_id` | int | 否 | 用户 ID（API 路由自动注入） |

### CLI 用法

```bash
python scripts/storyboard_agent_cli.py export-check \
  --storyboard-id 42 \
  --user-id 7
```

### 返回示例

```json
{
  "success": true,
  "storyboard_id": 42,
  "title": "第一集",
  "episode_number": 1,
  "total_scenes": 10,
  "ready_scenes": 8,
  "missing_scenes": 2,
  "details": [
    {
      "index": 3,
      "scene_id": 101,
      "title": "分镜3",
      "visual_type": "none",
      "audios": 2,
      "missing": ["video_missing"],
      "ready": false
    },
    {
      "index": 1,
      "scene_id": 99,
      "title": "分镜1",
      "visual_type": "video",
      "audios": 1,
      "missing": [],
      "ready": true
    }
  ]
}
```

### 字段说明

- **ready_scenes**：画面素材齐全且无 missing 标记的分镜数
- **missing_scenes**：有缺失的分镜数
- **details[].visual_type**：`video` / `image` / `none`
- **details[].missing**：缺失标记列表，如 `["video_missing"]`、`["no_media"]`、`["audio_1"]`

## export-full-video

将所有分镜合成一个完整 MP4（可选烧录对白字幕），上传 CDN 后返回下载链接。

### 参数

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `storyboard_id` | int | 是 | - | 故事板 ID |
| `user_id` | int | 是 | - | 用户 ID |
| `include_subtitles` | bool | 否 | `true` | 是否硬烧对白字幕（ASS 格式，超长分页） |

### CLI 用法

```bash
# 默认烧录字幕
python scripts/storyboard_agent_cli.py export-full-video \
  --storyboard-id 42 \
  --user-id 7

# 不烧录字幕
python scripts/storyboard_agent_cli.py export-full-video \
  --storyboard-id 42 \
  --user-id 7 \
  --no-subtitles
```

### 返回示例

```json
{
  "success": true,
  "download_url": "https://cdn.example.com/path/to/video.mp4",
  "filename": "第一集_完整_20260718_160000.mp4"
}
```

### 技术细节

- **同步执行**：CLI 为一次性脚本进程，同步等待合成完成后直接返回结果（不同于 API 的异步 job + 轮询模式）
- **合成流程**：`collect_export_plan` → 下载/转换媒体 → `build_merged_video`（ffmpeg concat + 可选字幕烧录）→ 上传 CDN
- **超时保护**：各 ffmpeg 步骤受 `EXPORT_FFMPEG_TIMEOUT_SECONDS`（300s）保护
- **字幕**：使用内置 CJK 字体（NotoSansSC），通过 ffmpeg `subtitles` 滤镜硬烧 ASS 字幕
- **audio_embedded**：若分镜视频已内嵌对话声音（如数字人产物），保留原音轨、跳过 TTS 混音

## export-package

将所有分镜素材（视频/图片 + 配音 wav）打包为 zip，上传 CDN 后返回下载链接。

### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `storyboard_id` | int | 是 | 故事板 ID |
| `user_id` | int | 是 | 用户 ID |

### CLI 用法

```bash
python scripts/storyboard_agent_cli.py export-package \
  --storyboard-id 42 \
  --user-id 7
```

### 返回示例

```json
{
  "success": true,
  "download_url": "https://cdn.example.com/path/to/assets.zip",
  "filename": "第一集_素材_20260718_160000.zip"
}
```

### ZIP 包结构

```
第一集_素材_20260718_160000.zip
├── manifest.json          # 导出清单（故事板元信息 + 分镜列表）
├── 分镜1.mp4              # 分镜1 视频（或 .png/.jpg 图片）
├── 分镜1_1.wav            # 分镜1 第1条配音
├── 分镜1_2.wav            # 分镜1 第2条配音
├── 分镜2.mp4
├── 分镜2_1.wav
└── ...
```

## API 调用方式

除 CLI 外，也可通过 API 调用：

```bash
# 获取 schema
GET /api/storyboard/agent/schema

# 执行命令
POST /api/storyboard/agent/commands/export-check
POST /api/storyboard/agent/commands/export-full-video
POST /api/storyboard/agent/commands/export-package
```

请求体为 JSON，包含命令参数（`user_id` 由 Authorization header 自动注入）。

## 相关文件

- `services/storyboard_agent_cli_service.py` — `export_check()`、`export_full_video()`、`export_package()` 方法
- `services/storyboard_agent_command_service.py` — schema 定义与命令分发
- `scripts/storyboard_agent_cli.py` — CLI argparse 入口
- `services/storyboard_export_service.py` — 底层导出服务（ffmpeg 合成、zip 打包、CDN 上传）
- `config/constant.py` — `StoryboardExportConstants`、`StoryboardTimeouts` 超时常量
