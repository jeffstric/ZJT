# 故事板自动对话配音

## 触发时机

在 `storyboard.html` 中执行“根据剧本生成分镜”后，后端会在分镜和对话行创建成功之后，自动为符合条件的 `storyboard_dialogue` 提交配音任务。

该步骤只负责提交任务，不等待 TTS 生成完成，因此不会阻塞剧本拆分接口。前端加载新分镜后，会根据接口返回的 `audio_auto_generate.submitted` 为相关分镜启动已有的 `/api/storyboard/scene/{scene_id}/task-status` 轮询。

拆分成功时，前端会把“已生成 N 个分镜”和“已提交 N 条配音任务，M 条跳过”合并为一次提示，避免连续弹出两个 alert。

## 数据链路

单条对话配音和自动配音共用同一条后端提交逻辑：

```text
storyboard_dialogue
  -> ai_audio(PENDING)
  -> tasks(generate_audio, QUEUED)
  -> storyboard_dialogue_audio(ai_audio_id)
  -> storyboard_dialogue.selected_audio_id
```

音频任务由 scheduler 异步处理。任务成功后：

```text
ai_audio.result_url
  -> storyboard_dialogue_audio.audio_url
```

`storyboard_dialogue_audio.audio_url` 是故事板侧的冗余持久化字段，用于重新加载故事板时恢复音频播放器。状态接口也会在该字段为空时兜底返回 `ai_audio.result_url`，兼容历史数据或偶发回写失败。

### 参考音频路径归一化（远程 TTS）

参考音频 `ai_audio.ref_path` 在数据库中可能存为三种格式：

- `/upload/character/voice/xxx.mp3`（RunningHub 生成配音写入，带前导斜杠）
- `upload/character/voice/xxx.mp3`（无前导斜杠的相对路径）
- `http://host/upload/character/voice/xxx.mp3`（手动上传写入的完整 URL）

调用远程 TTS（`utils/index_tts_util.py`）时，需先把上述任一格式通过 `utils.project_path.resolve_upload_url_to_local_path` 归一化为本地文件系统绝对路径，再判断 `os.path.isfile`：命中则经 `/upload_reference` 上传到 TTS 服务器，换取 TTS 侧本地路径后参与合成；未命中且非本地文件时原样透传。

> 直接对带前导斜杠的 `/upload/...` 调 `os.path.isfile` 会在文件系统根解析而误判为 False，导致跳过上传、把远程 TTS 不可达的路径原样透传，引发 `FileNotFoundError`。该 bug 已于 2026-07-06 修复。

### 分镜时长自动重算（配音完成后联动）

当某分镜下**所有对话的当前选中配音**都生成完毕时，系统自动把该分镜时长（`storyboard_scene.duration`）设为这些音频时长之和，并联动重算故事板总时长（`storyboard.total_duration`）。

> **字段类型**：`storyboard_scene.duration` 与 `storyboard.total_duration` 均为 `DECIMAL(10,3)` 浮点秒（迁移 `20260706_scene_duration_decimal`），保留毫秒级精度，避免音频求和被整数化截断导致短于音频。视频生成提交时统一 `math.ceil` 取整秒（`storyboard_agent_cli_service.py`），确保视频不丢帧、不短于音频。

**触发时机**（两处，覆盖自动生成与手动切换）：

1. 每条配音生成成功后（`task/audio_task.py:_submit_new_task` 成功收尾处，含 E2E Mock 分支），经 `_finalize_scene_duration_if_completed` 探测时长并调用重算。
2. 用户/agent 手动 `POST /dialogue/{id}/audio/select` 切换选中配音后（`api/storyboard.py:select_dialogue_audio`），覆盖"切换到一条**已完成的**配音"的场景（此时不会有新的音频完成事件触发，需主动重算）。

**判定与计算逻辑**（`StoryboardDialogueAudioModel.sum_selected_durations_if_all_completed`，单条 SQL 完成，状态值参数化引用 `AIAudioStatus.COMPLETED`）：

- 该分镜**无任何 dialogue** → 不触发（返回 None）。
- 任一 dialogue 的 `selected_audio_id` 为 NULL（未生成/未选中）→ 不触发。
- 任一选中配音对应的 `ai_audio.status` ≠ COMPLETED（处理中/失败）→ 不触发。
- 任一选中配音 `storyboard_dialogue_audio.duration` 为 NULL（时长尚未探测）→ 不触发。
- 全部满足 → 返回 `SUM(duration)`，写入 `storyboard_scene.duration = max(1.0, round(总和, 3))`（DECIMAL(10,3) 三位小数，下限 1.0 秒）。

**重算函数**：`task/audio_task.py:recalc_scene_duration_if_all_completed(scene_id)` 封装了"判定 + 写 scene.duration + 联动 recalc_total_duration"，供 finalize 与 select 两处复用。best-effort，所有异常仅记日志，不向上抛出、不阻塞调用方。

**时长探测与持久化**：每条配音生成成功时，用 ffprobe 探测 `result_url`（支持 HTTP URL）的时长并写入 `storyboard_dialogue_audio.duration`（生成时探测一次并存库，避免重算时反复探测）。探测失败只记日志，不影响音频本身的成功结果；待下次相关音频重新生成时补全。

**重新生成某条配音**：`set_selected` 指向新记录，新记录 status=PENDING → 该分镜重新进入"未全部完成"状态；新记录完成且全部完成后再次触发重算，覆盖旧 duration。

**前端即时刷新**：轮询接口 `GET /scene/{id}/task-status` 在原响应基础上新增扁平字段 `scene_duration`（当前分镜时长浮点秒，后端同步后即时反映）。前端 `web/js/storyboard/polling.js:applyTaskStatus` 读取该字段，更新 `scene.duration` / `scene.durationLabel`（`formatDuration` 仍 floor 为 `MM:SS` 显示，与时间线标签口径一致），并标记 `_durationChanged`；`applySceneUpdate` 据此调用 `render.js:updateTimelineProgress` 单独刷新进度行总时长 span（该 span 不随缩略图/预览的局部更新自动重渲）。总时长由前端 `getTotalDuration()` 从 `state.scenes` 求和得出，无需后端返回。

**关键文件**：

- `model/storyboard_dialogue_audio.py`：`duration` 字段、`sum_selected_durations_if_all_completed`、`update_duration_by_ai_audio_id`、`get_by_ai_audio_id`
- `model/storyboard.py`：`recalc_total_duration`（求和 + 写 `storyboard.total_duration`）
- `model/storyboard_scene.py`：`duration` 字段（DECIMAL(10,3)）
- `utils/audio_duration_util.py`：`get_audio_duration_seconds` / `probe_audio_duration`（ffprobe 探测，支持 HTTP URL 和本地路径，失败返回 None）
- `task/audio_task.py`：`recalc_scene_duration_if_all_completed`（重算公共函数）、`_finalize_scene_duration_if_completed`（生成成功联动主逻辑）、`_submit_new_task` 收尾处调用
- `api/storyboard.py`：`select_dialogue_audio`（切换配音后调用重算）、`get_scene_task_status`（返回 `scene_duration`）
- `config/constant.py`：`FFPROBE_AUDIO_DURATION_TIMEOUT`（探测超时，默认 30 秒）、`AIAudioStatus.COMPLETED`
- `web/js/storyboard/polling.js`、`web/js/storyboard/render.js`、`web/js/storyboard/adapters.js`（前端 duration 同步与局部刷新）

## 自动生成条件

会自动提交配音任务的对话需要满足：

- `dialogue.text` 非空。
- 当前没有 `selected_audio_id`。
- 能找到参考音频。

参考音频解析优先级：

1. 调用配置中的 `ref_path`。
2. 对话角色的 `character.default_voice`。

## 跳过情况

自动生成不会因为单条对话无法配音而让整个剧本拆分失败。不可生成的对话会进入 `audio_auto_generate.skipped`：

| reason | 含义 |
| --- | --- |
| `empty_text` | 台词为空 |
| `missing_reference_audio` | 角色没有默认参考音频 |
| `already_has_selected_audio` | 对话已有选中音频 |
| `limit_reached` | 达到单次拆分自动提交上限 |
| `narration_without_voice` | 旁白行暂未配置默认旁白音色 |
| `submit_failed` | 提交过程中出现非预期错误 |

目前 `character_id = NULL` 的旁白行会跳过。后续如果新增默认旁白音色配置，可在同一链路中放开。

## 前端表现

拆分接口返回示例：

```json
{
  "audio_auto_generate": {
    "enabled": true,
    "submitted_count": 12,
    "skipped_count": 2,
    "submitted": [
      {"dialogue_id": 101, "scene_id": 8, "audio_id": 501, "dialogue_audio_id": 301}
    ],
    "skipped": [
      {"dialogue_id": 102, "scene_id": 8, "reason": "missing_reference_audio"}
    ]
  }
}
```

前端会：

- 加载返回的 scenes。
- 对 `submitted` 中出现的 scene 启动任务轮询。
- 提示“已提交 N 条配音任务，M 条跳过”。
- 轮询拿到 `audio_url` 后展示已有的对话音频播放器。

## 相关文件

- `api/storyboard.py`
- `model/storyboard_dialogue.py`
- `model/storyboard_dialogue_audio.py`（含 `duration` 字段、`sum_selected_durations_if_all_completed`）
- `task/audio_task.py`（配音成功后联动分镜时长重算）
- `utils/index_tts_util.py`（远程 TTS 调用，含参考音频路径归一化与上传）
- `utils/audio_duration_util.py`（ffprobe 音频时长探测）
- `utils/project_path.py`（`resolve_upload_url_to_local_path` 路径归一化工具）
- `web/js/storyboard/events.js`
