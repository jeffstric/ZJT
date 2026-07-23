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
| 拆分弹窗最小化/重开 | `modal` + `header`（+ `leftTabBody` 空板恢复入口） |
| 拆分轮询进度（最小化态） | `header`（仅徽章百分比） |

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

## 拆分进度弹窗最小化

拆分进度弹窗（`renderGenerateProgressDialog`）支持「最小化」：进行中点 X 按钮可关闭弹窗，任务在后端继续运行，Header 右上角出现常驻徽章作为重开入口。

### 状态语义

| 字段 | 含义 |
|------|------|
| `isGeneratingFromScript` | 任务处于活跃运行态（不论弹窗开关） |
| `showGenerateProgressDialog` | 进度弹窗是否展示 |
| `generateFromScriptTaskId` | 拆分任务 ID（关闭弹窗不清，完成/重试才清） |
| `generateProgressError` | 错误/暂停文案（空=进行中） |

**关键原则**：关闭弹窗 ≠ 停止任务。进行中最小化时**保留 taskId 与 isGeneratingFromScript**，仅停弹窗渲染；轮询继续，徽章百分比实时更新。

### 交互闭环

| 操作 | 触发 | regions |
|------|------|---------|
| 进行中点 X（最小化） | `close-generate-progress`（`isGeneratingFromScript=true` 分支：不停轮询） | `modal` + `header` + `leftTabBody` |
| error/暂停态点 X（关闭） | `close-generate-progress`（`isGeneratingFromScript=false` 分支：停轮询） | `modal` + `header` + `leftTabBody` |
| 点 Header 徽章重开 | `reopen-generate-progress` → `reopenGenerateProgressDialog()`（幂等重启轮询） | `modal` + `header` |
| 轮询 onUpdate（弹窗开） | `updateGenerateProgressStepsByStatus` | `modal` |
| 轮询 onUpdate（最小化） | `updateGenerateProgressStepsByStatus` | `header`（仅徽章进度） |
| 任务完成（onComplete） | 清 taskId → 徽章自然消失 | `all` + `forcePreview` |
| 任务出错（弹窗开） | `onError`：展示错误 + 重试按钮 | `modal` |
| 任务出错（已最小化） | `onError`：不强制弹窗，徽章转红色「拆分待处理」脉冲提示 | `header` + `leftTabBody` |

### 入口位置

- **Header 常驻徽章**（`renderHeaderSplitBadge`）：`generateFromScriptTaskId && !showGenerateProgressDialog` 时渲染，进行中蓝色 + spinner，错误态红色脉冲。非空板也能见。
- **左栏空板恢复按钮**（`renderTabs` 空板分支）：仅 `!scene` 时显示「查看拆分进度」，与徽章并存。

### 防误触

进行中点遮罩**不关闭**弹窗（`events.js` 遮罩拦截保留），仅 X 按钮可最小化。
