# 故事板对口型（digital_human）分镜

## 语义

| 字段值 | 产品名 | 说明 |
|--------|--------|------|
| `video` | 视频 | 图生视频（首帧 → i2v） |
| `digital_human` | **对口型** | 单人说话镜头；**固定 MiniMax H3 数字人** |
| `image` | 图片 | 仅画面，不生视频 |

`video_type` 落在 `storyboard_scene.video_type`（`SceneVideoType`）。

> **视频原声**：数字人分镜 `audio_embedded` 默认为 `1`（前端「音频来源 → 视频原声」）。MiniMax 产物已内嵌口型音轨，时间轴连续预览和完整视频导出均保留视频原音轨、跳过 TTS。

## 生成两阶段（必须串行）

```
阶段 A TTS：台词 + character.default_voice → dialogue.audio_url
阶段 B MiniMax H3：image + 成片说话音频 + 动作 prompt → ai_tools type=35
```

- **禁止**无配音提交对口型视频。
- 任务类型常量：`StoryboardDigitalHumanConstants.TASK_TYPE` = `DIGITAL_HUMAN_MINIMAX_H3`（35）。

服务：

- `orchestrate_digital_human_generation` / `submit_digital_human_plan`
- 入口：`POST /api/storyboard/scene/{id}/generate-video`（按 `video_type` 分发）
- 批量：`auto-generate-missing-videos`
- CLI：`generate-video`（对口型分镜自动分流）
- Agent：`generate_digital_human`

## 输入对照（MiniMax H3）

| 输入 | 来源 |
|------|------|
| 图片 (209) | 当前分镜**选中的首帧** |
| 音频 (215) | 对话 TTS 成片（多段合并） |
| prompt (214) | 写死：`图片1中的角色在说话。` |
| 时长 (212) | TTS 总时长 ceil 后 **clamp 到 4–10 秒** |
| 最长边 (213) | 故事板视频分辨率偏好映射：480P→720 / 720P→1280 / 1080P→1920 |
| 开始说话秒 (229) | 固定 0 |

## 分辨率

齿轮弹窗「图生视频模型」下方的分辨率 chip 为故事板级偏好 `state.videoResolution`，对口型与图生视频共用。  
生成时 body 带 `resolution`，服务端写入 `extra_config.max_edge`。

## 前端

- 时间轴角标「对口型」
- 助手提示条：`对口型 · MiniMax H3 · 配音状态`
- 直连「视频生成」：无需填提示词；需已选中首帧 + 配音就绪
