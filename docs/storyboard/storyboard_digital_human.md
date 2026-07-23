# 故事板对口型（digital_human）分镜

## 语义

| 字段值 | 产品名 | 说明 |
|--------|--------|------|
| `video` | 视频 | 图生视频（首帧 → i2v） |
| `digital_human` | **对口型** | 单人说话镜头；**仅 LTX2.3 数字人** |
| `image` | 图片 | 仅画面，不生视频 |

`video_type` 落在 `storyboard_scene.video_type`（`SceneVideoType`）。

> **视频原声**：数字人分镜 `audio_embedded` 默认为 `1`（前端「音频来源 → 视频原声」）。LTX2.3 产物已内嵌口型音轨，时间轴连续预览和完整视频导出均保留视频原音轨、跳过 TTS（见 `storyboard_export.md`）。该设置为分镜级，可在「对话」页签手动切换。

## 拆分判定

剧本拆分时：

1. **说话角色数 ≠ 1**（无对白 / 旁白 / 多人）→ 强制 `video`
2. 单说话人 + 强动作（打斗/追逐等）→ `video`
3. 单说话人 + LLM `presentation=digital_human` 或近景启发式 → `digital_human`

实现：`services/storyboard_scene_type.py`；落库于 API / CLI 的 `build_*_from_parsed_script`。

## 生成两阶段（必须串行）

```
阶段 A TTS：台词 + character.default_voice → dialogue.audio_url
阶段 B LTX2.3：image + **成片说话音频** + 动作 prompt → ai_tools type=32
```

- **禁止**无配音提交对口型视频。
- **禁止** wan 数字人（type=13）：其音频是参考音色、说话内容靠文本，与 LTX 语义不同。
- 任务类型常量：`StoryboardDigitalHumanConstants.TASK_TYPE` = `DIGITAL_HUMAN_LTX2_3_VOICE`。

服务：

- `ensure_storyboard_dialogue_audio_ready`
- `submit_storyboard_digital_human_video`
- 入口：`POST /api/storyboard/scene/{id}/generate-video`（按 `video_type` 分发）
- 批量：`auto-generate-missing-videos` 对对口型检查配音后走 LTX 提交

## 输入对照（对齐工作流 LTX 数字人）

| 输入 | 来源 |
|------|------|
| 图片 | 当前分镜**选中的首帧**（`asset.result_url` 为空时用 `ai_tool.result_url` 兜底，与 assets 接口一致；不再回退角色参考图） |
| 音频 | 对话 TTS **结果**（口型驱动源） |
| prompt | `video_prompt` 或默认动作句（非台词正文） |

## 前端

- 时间轴角标「对口型」
- 批量按钮：配音未就绪显示「对口型待配音」；就绪后与普通镜一并提交
- “画面”面板顶部可在“视频模式 / 对口型”之间切换。切换通过
  `PUT /api/storyboard/scene/{scene_id}/video-type` 原子更新，不删除已有候选或取消任务。
- 对口型切换为视频模式后，已完成且当前选中的对口型成片继续使用；如果当前选中的是运行中的旧模式任务，改为最近一个已完成的视频候选。旧任务完成后只进入候选，不自动重新选中。
- 多个说话角色的分镜不能切换为对口型；没有配音的单说话人分镜可以切换，但生成前仍需完成配音。
- 切换不会自动修改 `audio_embedded`，确保继续使用旧对口型成片时不会重复混入 TTS。
- 分镜助手的视频模式提示读取当前分镜的对话音频状态：存在 `audioUrl/audio_url` 时显示「配音已就绪」；状态为 pending/queued/running/processing（含数值 0/1）时显示「配音生成中」；其余显示「需先配音」。

### 对口型分镜的直连「视频生成」模式

对口型分镜在分镜助手切到「视频生成」（`chatMode === 'video'`，直连 `generate-video`，不走智能体）时，一键生成、无需填写提示词：

- 不渲染视频提示词文本框（`render.js` `renderAiPanel()` 的 `isDhDirectVideo`），助手区只保留「对口型 · LTX2.3 · 配音状态」提示条与工具栏；发送按钮 title 提示「生成数字人对口型视频」。
- 点发送即提交：前端只校验「已选中首帧」和「成片配音已就绪」，不校验提示词与图生视频模型，请求体不带 `prompt`/`task_type`（后端数字人分支本就忽略这两项，提示词由服务端用台词或 `DEFAULT_PROMPT` 规划、固定 LTX2.3 路由）。
- 配音未就绪时点发送：toast 提示并自动切到「对话」Tab，与「AI生视频」模式行为一致。
- 「AI生视频」（aivideo，智能体链路）不受影响，仍需输入消息。

### 分镜助手的视频发送按钮

分镜助手的蓝色发送按钮走 `POST /api/storyboard/scene/{id}/ai-chat`，不是直接调用
`generate-video` 接口。后端必须按当前 `storyboard_scene.video_type` 限制 Agent 工具：

- `digital_human`：只暴露分镜专用 `generate_digital_human`（以及查询算力、询问用户等辅助工具），禁止暴露 `image_to_video` 和 `generate_text_to_video`。
- 普通 `video`：继续按有无输入帧选择 `image_to_video` 或 `generate_text_to_video`。
- 分镜专用数字人工具不接收图片或音频 URL；服务端从当前分镜解析角色图和已完成配音，固定提交 `StoryboardDigitalHumanConstants.TASK_TYPE`（LTX2.3）。
- 提交前按 LTX2.3 配置扣除算力；提交服务会直接创建并选中 `StoryboardSceneAsset(video)`，事件携带 `already_bound=true`，前端只刷新候选和任务状态，不得再次绑定，避免重复候选记录。

实现位置：

- 提示词和 Runner：`api/storyboard.py`
- 工具白名单、算力扣除与分镜级适配器：`services/storyboard_agent_video_tool.py`
- SSE 任务回绑处理：`web/js/storyboard/events.js`
