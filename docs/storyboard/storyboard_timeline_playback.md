# 故事板时间轴预览播放

## 概述

`web/storyboard.html` 时间轴控制条上的播放按钮支持**类剪影的分镜连续预览**：按分镜顺序播放选中画面（视频优先，否则定格分镜图），并同步串行播放该分镜下各对话的选中配音。

实现模块：`web/js/storyboard/playback.js`。

## 媒体规则

| 资源 | 字段 | 行为 |
|------|------|------|
| 视频 | `scene.videoUrl` | 优先播放；预览时 **muted**（对白走配音轨）；`loop=false` |
| 分镜图 | `scene.firstFrameUrl` | 无视频时定格展示 |
| 配音 | `scene.dialogues[].audioUrl` | 按 `sortOrder` **串行**；音量用 `volume`（0–100 或 0–1） |
| 分镜时长 | `scene.duration` | **本镜占用与播放头分母**；配音全部完成后由后端同步为选中配音时长之和（见 `storyboard_auto_dialogue_audio.md`，前端 `polling` 读 `scene_duration`） |

### 单镜占用时长（权威）

```
sceneSpan = scene.duration > 0 ? scene.duration : EMPTY_HOLD_FALLBACK(2s)
```

- **不使用**视频 `duration` 作为本镜时长或切镜条件  
- 镜内播放头比例：`sceneLocalTime / sceneSpan`（再映射到该卡片宽度）  
- 全局 `currentTime`：已完成镜的 `duration` 累加 + 镜内本地时间  

### 起播前预加载

进入本镜后、**开时钟之前**：

1. 挂载 video / img  
2. 并行预载：视频 `readyState >= HAVE_FUTURE_DATA`、图片 load、**全部**对白 `Audio` canplay  
3. 预览显示「加载中…」遮罩；`sceneLocalTime` 保持 0  
4. 就绪（或单资源超时 20s best-effort）后：关遮罩 → `startClock` → 同步播视频 + 预载好的配音队列  

避免「时间轴已走、媒体仍在缓冲」。

### 音画与切镜

本镜**唯一结束条件**：媒体就绪后墙钟走到 `sceneSpan` → 进入下一镜（`runLoop` 递增）。

| 情况 | 行为 |
|------|------|
| 有对白 + 视频 | 同时开始；对白串行；到 `sceneSpan` 截断音画并切下一镜 |
| 视频短于 `sceneSpan` | 视频 `ended` 后定格末帧，等到 span 结束再切镜 |
| 视频长于 `sceneSpan` | **截断视频**，不卡在本镜等 `video.ended` |
| 仅图 | 定格至 `sceneSpan` 结束 |
| 无配音 | 仍按 `scene.duration`（或 2s fallback）推进 |

> 配音齐后 `scene.duration` ≈ 对白时长和，故进度与听感对齐。未齐时以当前库内 `duration` 为准。

## 交互

1. **起点**：点击分镜选中后点播放 → **从该分镜**播到最后；`ended` 后再点播放仍跟**当前选中镜**，不强制回片头。  
2. **选中分镜**：`stopPlayback` + `syncSelectionToTimeline`（`currentTime` = 该镜起点，`status=idle`）。  
3. **暂停 / 继续**：同一按钮；冻结 video + 当前 audio。  
4. **字幕**：勾选「字幕」时显示当前对白文本。  
5. **停播**：点其他分镜、键盘左右切镜、切 grid、全量 `renderApp`、页面隐藏/卸载。  
6. **播放头**：`.scene-timeline-playhead` 按 **当前分镜索引 + 镜内 `sceneLocalTime/sceneSpan` 比例** 定位到对应卡片；水平坐标用 `getBoundingClientRect` 相对 list 换算（不可用 thumb.offsetLeft，因 item/thumb 为 `position:relative` 会导致恒为 0 而钉在第一镜）；播放中/选中时自动滚入视口。  

## 架构约束

- 播放路径**不**用全量 `rerender()` 驱动时钟。  
- 视频任务**不**进入切镜的 `await` 关键路径；`waitMs(sceneSpan)` 是唯一 await 的进度条件。  
- `renderApp` 入口 `onDomWillRerender()` 停播。  

## 关键文件

| 文件 | 职责 |
|------|------|
| `web/js/storyboard/playback.js` | 播放状态机、音画编排、playhead |
| `web/js/storyboard/state.js` | `isPlaying` / `currentTime` / `playback.*` |
| `web/js/storyboard/events.js` | `toggle-play`、选镜/切视图停播与时间对齐 |
| `web/js/storyboard/render.js` | 字幕层、playhead DOM、`onDomWillRerender` |
| `web/js/storyboard/bootstrap.js` | visibility / pagehide / resize |
| `web/css/storyboard.css` | `.preview-subtitle`、`.scene-timeline-playhead` |

## 状态字段

```js
state.isPlaying
state.currentTime
state.subtitleEnabled
state.playback = {
  sceneId,
  sceneLocalTime,
  audioDialogueId,
  status,       // idle | playing | paused | ended
  generation,
}
```

## 后续可选

- 拖拽 playhead seek  
- 进度条 scrub  
- 预览「裁到配音」与导出开关对齐  
