# 分镜时长同步链路（音频 → scene.duration → 视频时长）

记录 `storyboard_scene.duration` 的取值来源、各阶段精度约定，以及视频生成入口的「时长兜底刷新」机制。本文档配合修复 commit：分镜时长浮点丢失导致视频时长不够。

## 背景

用户反馈：故事板根据音频推算的分镜时长不准确，没有将浮点部分加入，导致音频生成后视频时长不够。

排查后确认存在**两个独立缺陷**，分别在「显示层」与「生成时序层」，根因不在传统的取整截断（后端 `round(_, 3)` 保留毫秒、视频量化用 `ceil` 方向正确），而在于：

1. **显示层丢小数**：前端时长标签 `formatDuration` 经 `parseDurationSeconds` 对数字 `Math.round`，秒的小数被抹掉。
2. **生成时序窗口**：TTS 完成回写 `scene.duration` 是 best-effort 联动，视频生成可能在回写前触发，拿到的是剧本拆分阶段 LLM 估算的整数秒，而非真实音频浮点时长。

## duration 取值的三个阶段

| 阶段 | 代码位置 | 取值 | 精度 |
|---|---|---|---|
| ① 剧本拆分初值 | `llm/script_parser.py` prompt + `api/storyboard.py:build_storyboard_scenes_from_parsed_script` | LLM 按**台词文字**估算（prompt 写「通常 3-6 秒」，示例值 `5.0`/`4.0` 整数）→ `_safe_float` → `create_scenes` 落库 | 整数秒（LLM 估算，非真实音频） |
| ② TTS 完成回写 | `task/audio_task.py:recalc_scene_duration_if_all_completed` | ffprobe 探测每条 TTS 时长 → `StoryboardDialogueAudioModel.sum_selected_durations_if_all_completed` 求和 → `round(_, 3)` → 写 `storyboard_scene.duration`（DECIMAL(10,3)） | 毫秒级浮点，**真值** |
| ③ 视频生成量化 | `api/storyboard.py:_resolve_storyboard_video_duration_seconds` / 前端 `state.js:resolveVideoDurationSeconds` | 读 `scene.duration` → `auto` 模式选「≥ target 的最小模型档位」；无档位表时 `ceil` 兜底 | 整数秒（模型档位） |

> 第 ③ 步的量化方向是「向上/向档位对齐」（ceil 或选更大档位），**视频时长必然 ≥ 音频时长**，本身不会让视频短于音频。问题只在于第 ③ 步拿到的 `scene.duration` 是否已是第 ② 步的真值。

## 第 ② 步回写是 best-effort

`recalc_scene_duration_if_all_completed` 由配音任务完成事件触发（`_finalize_scene_duration_if_completed`），任何步骤失败都只记日志、不抛出。因此存在窗口：

- TTS 音频已生成（ffprobe 可测时长）
- 但回写 `scene.duration` 的异步链路尚未跑完
- 此时若触发视频生成，读到的是第 ① 步的 LLM 估算整数秒

## 修复方案

### A. 显示层（前端，`web/js/storyboard/adapters.js` + `utils.js`）

`formatDuration` 改为**不依赖** `parseDurationSeconds`（后者对数字做 `Math.round` 会丢小数），自行解析原始浮点值，秒部分保留 1 位小数：

- `formatDuration(7.4)` → `00:07.4`
- `formatDuration(7)` → `00:07`（整数不追加 `.0`）
- `formatDuration(67.45)` → `01:07.5`
- `formatDuration("01:07")` → `01:07`（字符串兼容）

约束：
- **`parseDurationSeconds` 不改**（它服务于「MM:SS 字符串解析回数字」等场景，改了会连带影响其它逻辑）。
- `scene.duration` 真值始终保留浮点（`sceneFromApi` 对 number 原样保留，仅字符串/undefined 降级走 `parseDurationSeconds`）。
- 所有 `formatDuration` 调用点（`durationLabel` 构造、进度条、时间线、媒体签名）均为纯显示，不参与时长计算，改动安全。

### B. 生成时序层（后端兜底刷新，方案 B2）

在**每条视频生成入口**读取 `scene.duration` 之前，主动调用 `recalc_scene_duration_if_all_completed(scene_id)` 尝试用真实音频时长刷新：

- 全部配音完成 → 覆盖 `scene.duration` 为真实浮点时长，重新读取 scene 对象
- 仍有未完成配音 → 返回 `None`，保持原值（best-effort，不阻断）
- 刷新本身异常 → 仅记日志，继续走原 duration

覆盖的三处入口：

| 入口 | 文件:函数 | 说明 |
|---|---|---|
| 单镜视频生成 | `api/storyboard.py:generate_scene_video` | 图生视频 HTTP 接口，刷新点在量化前 |
| AI 助手对话生成视频 | `api/storyboard.py:scene_ai_chat` | `generation_target == 'video'` 分支开头刷新 |
| 批量/CLI 视频生成 | `services/storyboard_agent_cli_service.py:generate_video` | 同步上下文，直接调 `sum_selected_durations_if_all_completed` 覆盖 scene dict |

> CLI 路径是同步方法（跑在 `to_thread` 线程里），不能直接 `await` async 函数；改为直接调用同步 model 方法 `StoryboardDialogueAudioModel.sum_selected_durations_if_all_completed(scene_id)`，避免 `asyncio.run` 跨事件循环包装（遵循 AGENTS.md 超时红线）。

## 已确认安全（无需改动）

- `task/audio_task.py:74` `round(float(total), 3)`：保留毫秒，非截断。
- `model/storyboard.py:recalc_total_duration`：浮点求和。
- `_resolve_storyboard_video_duration_seconds` / `resolveVideoDurationSeconds`：`ceil` / 选 ≥ target 最小档位，方向正确。
- `model/storyboard_scene.py` `to_dict`：`float(self.duration)` 把 DECIMAL 转 number，前端收到的是 JS number（非字符串），走 `sceneFromApi` 的 number 分支保留浮点。
- `create_scenes` / `_safe_float`：不二次取整。
- 导出阶段 `services/storyboard_export_service.py`：`span = scene.duration`（浮点），视频短于 span 时 `tpad` 定格补帧；最终片段时长 = 音频浮点时长，不等于生成的整数视频时长。

## 验证

- 前端 `formatDuration`：16 个边界用例（整数/小数/四舍五入/分钟进位/null/undefined/字符串）全部通过。
- 后端：`python -m py_compile` 语法编译通过；`scripts/lint_blocking_calls.py` 退出码 0，R4/R6 无违例。
