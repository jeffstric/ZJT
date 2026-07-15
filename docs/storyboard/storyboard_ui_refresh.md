# 故事板 UI 分区刷新

## 目标

默认**禁止** `app.innerHTML` 全量重建。业务改 state 后通过 `refresh(regions)` 只更新脏区，避免：

- 主预览 video 被拆掉（播到一半停）
- 左侧表单焦点/滚动丢失
- Agent SSE / 轮询导致整页闪烁

## 入口

| API | 说明 |
|-----|------|
| `refresh(regions, options?)` | 主入口，`web/js/storyboard/render.js` |
| `Region.*` | 区域常量，`web/js/storyboard/ui_regions.js` |
| `renderApp()` | 兼容别名 → `refresh('all')`（仍受 preview busy 保护） |
| `renderAppFull()` | 内部：唯一整页 `innerHTML`（首屏 / 无壳 / 明确 all 且非 busy） |

```js
import { refresh, Region } from './render.js';

refresh([Region.AGENT_LOG]);
refresh([Region.MODAL]);
refresh([Region.LEFT_SIDEBAR, Region.PREVIEW, Region.CANDIDATES], { forcePreview: true });
refresh('all'); // 仅启动、拆分后整表重建等
```

## 区域一览

| Region | 作用 |
|--------|------|
| `header` / `headerPower` | 顶栏 / 仅算力数字 |
| `leftSidebar` | 左栏工作台 + 助手 |
| `agentLog` / `agentPanel` | 助手消息 / 整块助手 |
| `preview` | 主预览（busy 时自动跳过，除非 `forcePreview`） |
| `center` | 中栏 timeline/grid |
| `timelineList` / `timelineChrome` / `grid` | 时间轴子集 |
| `candidates` | 右侧候选 |
| `modal` | 所有弹层（`[data-region=modals]`） |

预设：`REGIONS_ON_SCENE_CHANGE`、`REGIONS_AGENT_STREAM`、`REGIONS_MODAL`。

## 预览保护

`isPreviewMediaBusy()`（时间轴试看 **或** 原生 `video.controls` 播放中）：

- `refresh` 自动剔除 `preview` / `center`（除非 `forcePreview`）
- `refresh('all')` 降级为 soft 补丁（log / 算力 / 候选 / 进度），不 `onDomWillRerender`
- `patchPreview`：busy 时只改 caption；否则优先改 `src`

## 调用约定

| 场景 | regions |
|------|---------|
| Agent SSE | `agentLog` |
| 算力 | `headerPower` |
| 弹窗开闭 | `modal` |
| 助手字号/模式/媒体栈 | `agentPanel` |
| 切分镜 | `REGIONS_ON_SCENE_CHANGE` + `forcePreview`（含整块 leftSidebar） |
| 切画面/对话 Tab | `leftTabs` + `leftTabBody`（**不**重挂助手） |
| 增删对话 / 提示词 blur / 场景道具 | `leftTabBody` |
| 保存分镜字段 | `leftTabBody` + `sceneChrome` + preview/timeline |
| 轮询 task-status | 现有 `updateSceneThumb` 等，**不要** refresh all |
| 首屏 / 拆分重建整表 | `all` + `forcePreview` |

### 左栏拆分

- `patchLeftWorkspace()`：只写 `.sidebar-content`（标题/Tab/画面|对话），**保留**焦点与滚动，不碰 `.ai-chat-section`
- `patchLeftSidebar()`：整块左栏（切镜时用）

### 中栏 / 时间轴（Phase 3）

| API | 行为 |
|-----|------|
| `patchTimelineListStructure` | 只重建 `.scene-timeline-list` 内部，**不**碰 preview |
| `patchGridStructure` | 只重建 `.storyboard-grid` |
| `patchTimelineListOrGrid` | 比较 `data-scenes-sig`：同结构 → 单卡 thumb + 选中态；变结构 → 上两项 |
| `patchCenter` | 同 viewMode 时降级为 list/grid 结构 patch；viewMode 切换才整块 center |
| `syncTimelineSelectionActive` | 只改 active class |

增删分镜用预设 `REGIONS_ON_SCENE_STRUCT`（含 TIMELINE_LIST/GRID，不含整页）。

## CI

```bash
python scripts/lint_storyboard_render.py
```

- R1：`events.js` 禁止 `renderApp(`
- R2：禁止 bare `rerender()`
- R3：除 `render.js` 外禁止 `app.innerHTML =`

## 与播放文档

见 `storyboard_timeline_playback.md`：播放路径不依赖全量 rerender。
