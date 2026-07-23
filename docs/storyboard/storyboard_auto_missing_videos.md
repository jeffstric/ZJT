# 故事板批量生成缺失视频

## 目标

在 `storyboard.html` 时间轴「分镜序列」标题行，提供与「补全首帧」并列的 **批量生成视频** 入口：对已有首帧、尚无完成视频的分镜批量提交图生视频任务。

## 入口

- 位置：时间轴 `auto-complete-header` 右侧，补全按钮之后
- 文案示例：
  - 空闲有待生成（首尾帧模式）：`批量生成视频 (N)`
  - 空闲有待生成（全能参考模式）：`全能参考批量生成视频 (N)`
  - 进行中：`视频生成中 x/y`
  - 无首帧：`需先补全画面`（disabled）
  - 已齐：`视频已全部生成`（disabled）

## API

```http
POST /api/storyboard/{storyboard_id}/auto-generate-missing-videos
Authorization: Bearer <token>
Content-Type: application/json

{
  "limit": 12,
  "ratio": "16:9",
  "task_type": 可选视频模型 task_id,
  "sequence_mode": "speed",
  "continue_on_error": true,
  "image_mode": "first_last_frame"
}
```

`image_mode` 取值：

| 取值 | 含义 | 参考图来源 |
|------|------|-----------|
| `first_last_frame`（默认） | 首尾帧模式 | `[选中首帧, 选中尾帧]`（尾帧可选，无则仅首帧） |
| `multi_reference` | 全能参考模式 | `[选中首帧] + [角色/场景/道具参考图] + [全局画风参考图]`，去重保序 |

`image_mode` 缺省为 `first_last_frame`。前端沿用用户在齿轮配置里选的视频模式（已持久化到 storyboard `config_json`）。


返回结构与图片批量类似，含 `batch_id`、`items`、`status`。

进度轮询复用：

```http
GET /api/storyboard/image-batches/{batch_id}/status
```

（`asset_type=video` 的 job 存在同一张编排表。）

## 后端行为

- 命令：`auto-generate-missing-videos` → `StoryboardAgentCliService.auto_generate_missing_videos`
- 规划：
  - `video_type=video`：无完成视频且有首帧 → pending；无首帧 → skipped
  - `video_type=digital_human`：无完成视频且**成片配音就绪** + 有形象/首帧 → pending；缺配音 → skipped（`missing_audio` / `audio_pending`）
  - 已有视频 → completed；生成中 → running
- 调度：`_process_one_video_batch_job` 按分镜类型分支：
  - 普通镜 → `generate_video(mode=image_to_video, image_mode=<job.extra_json.image_mode>, task_type=<job.extra_json.task_type>)`，task_type 沿 `generate_video` → `submitter.image_to_video` → `video_tools.image_to_video` 一路透传到模型选择，**优先于用户偏好/默认回退**；传入的 task_type 无效（不存在/已禁用/类别不符）时记 warning 并降级，不中断批次
  - 对口型 → `submit_storyboard_digital_human_video`（**仅 LTX2.3 type=32**，禁止 i2v / wan）
- `task_type` 与 `image_mode` 一起写入 `job.extra_json` 与幂等性 payload（不同取值视为不同批次，不互相吞并）；调度时若所选 `task_type` 的模型 `supported_image_modes` 不含该模式，自动降级为 `first_last_frame` 并记 warning
- 幂等：同 storyboard + asset_type=video + image_mode 活动批次冲突返回 409 `active_batch_exists`

## 视频生成模式（首尾帧 / 全能参考）

批量生成视频沿用用户在齿轮配置里选的视频图片模式，两种模式语义对齐手动对话（分镜助手·视频模式）：

### first_last_frame（首尾帧模式，默认）

- `image_mode=first_last_frame`
- 参考图：`[选中首帧, 选中尾帧]`，无尾帧则仅首帧
- 适用：镜头起幅明确、需要精确控制起止画面的场景
- 模型要求：`supports_last_frame=True`（如 Seedance 2.0 / 2.0 Fast / 2.0 Mini、可灵 v2.5-turbo、Vidu-Q2-pro-fast）

### multi_reference（全能参考模式）

- `image_mode=multi_reference`
- 参考图集（去重保序）：

  | 序位 | 来源 | 字段 | 作用 |
  |------|------|------|------|
  | 1 | 选中首帧 | `storyboard_scene_asset(first_frame).result_url` | 画面主体一致（主参考） |
  | 2..N | 角色/场景/道具参考图 | `context.reference_images`（`_collect_reference_image_items` 收集） | 角色/场景/道具一致性 |
  | N+1 | 全局画风参考图 | `storyboard.style_reference_image` | 画风一致 |

- 适用：多张参考图综合驱动，需要统一画风/角色/场景一致性的场景
- 模型要求：`supported_image_modes` 含 `multi_reference`（如 Seedance 2.0 系列、VEO3、Grok）
- 注意：批量 multi_reference **不再要求尾帧**，但**仍要求选中首帧**（首帧是主参考，保证视频与分镜画面相关）

### 模型能力约束

| 模型能力字段 | 配置位置 | 影响 |
|-------------|---------|------|
| `supported_image_modes` | `config/unified_config.py` 各模型配置 | 决定模型可选的模式；前端模式选择器据此过滤 |
| `supports_last_frame` | 同上 | 仅影响首尾帧模式是否可用 |
| `supports_ref_audio_video` | 同上 | 仅影响参考视频文件（本功能不涉及） |

若用户选了 multi_reference 但当前模型不支持，前端按钮 title 提示「将使用首尾帧模式」，后端调度时也会防御性降级。

## 输入首帧来源（重要）

图生视频必须使用**当前分镜选中的** `storyboard_scene_asset(first_frame).result_url`（单格图，通常在 `upload/storyboard/first_frame/`）。

效果模式九宫格拆分后，多个 first_frame asset 可能共享同一个 `ai_tool_id`：

| 字段 | 含义 |
|------|------|
| `asset.result_url` | 单格分镜图（正确输入） |
| `ai_tools.result_url` | 整张宫格 temp 图（禁止用作视频首帧） |

`StoryboardAgentCliService._asset_info` 必须 **asset 优先、tool 仅兜底**，与 `api/storyboard.py::_asset_task_info` 一致。  
若误用宫格整图，历史任务的「输入图片」会显示 2×2 拼图，视频结果也不对。


详见 `docs/storyboard/storyboard_digital_human.md`。

## 前端

| 文件 | 作用 |
|------|------|
| `auto_missing_videos_state.js` | 批次状态、按钮 VM、sessionStorage |
| `auto_missing_videos.js` | 提交、恢复、轮询 |
| `render.js` | 时间轴按钮 |
| `events.js` | `auto-complete-missing-videos` |
| `bootstrap.js` | 打开页面恢复进行中批次 |

## 与「补全首帧」关系

| | 补全首帧 | 批量视频 |
|--|----------|----------|
| 对象 | 无首帧分镜 | 有首帧、无视频分镜 |
| 按钮 | 蓝色补全 | 绿色视频按钮 |
| 前置 | 无 | 建议先补全首帧 |
