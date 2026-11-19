# 时间轴 v2 多轨（剪映式）与垃圾桶（回收站）

> 涉及页面：`web/video_workflow.html`
> 实施分支：`develop_timeline_v2`（2026-11-19）

## 一、功能总览

| 功能 | 说明 |
|---|---|
| 垃圾桶（回收站） | 删除的画布节点 / 时间轴片段可恢复，随 workflow_data 持久化（跨会话、跨设备） |
| 时间轴 v2 多轨 | 视频/音频各最多 6 轨，片段绝对定位（秒），支持拖拽移动、跨轨、边缘裁剪、播放头分割、Ctrl 多选、缩放 |
| 撤销 | 时间轴工具栏「↩ 撤销」按钮（Ctrl+Z 同效）：暂停播放后回滚到上一份工作流快照 |
| 面板高度可调 | 时间轴顶部边缘拖拉把手（上下拖调高度 200~视口上限，双击恢复默认 340）；高度存 localStorage（本机 UI 偏好，不进 workflow_data）；画布让位/小地图/缩放控件经 CSS 变量 `--tt-panel-h` 与面板高度联动 |
| 音频磁吸 | 音频片段拖拽时对视频/音频片段边缘、播放头、0 点磁吸（阈值 12px，比视频 8px 更宽），命中时显示橙色磁吸指示线，方便对齐视频分段口 |
| 播放预览 | 时间轴内嵌预览窗，播放头（定时器驱动）+ 视频取最上层活跃片段 + 音频多轨并行 |
| 插入素材 | 仅经画布：节点「加入时间轴」按钮（落播放头处第一个空闲轨）。时间轴不提供直接导入媒体入口（素材必须先进画布节点） |
| 导出所见即所得 | 「导出剪影草稿」按时间轴绝对布局生成（片段带 `timeline_start` 时走后端绝对模式） |

## 二、数据结构（`state.timeline` / `state.trash`）

时间轴 clip 新增字段（视频 `state.timeline.clips` / 音频 `audioClips` 同构）：

```js
{
  id, nodeId, url, name, duration,
  startTime: 0,      // 源内剪切起点（秒）
  endTime: duration, // 源内剪切终点（秒）
  order, pillarId,   // 柱子（分镜分区）归属，保留作背景色带与旧导出兼容
  start: 0,          // v2 新增：时间轴绝对位置（秒）
  track: 0,          // v2 新增：轨号（视频 0~5 / 音频 0~5）
}
```

`state.timeline` 新增：`version: 2`、`videoTrackCount`、`audioTrackCount`、`zoom`（pxPerSec，10~200）、`playhead`（秒）、`selectedClipIds`（多选）、`playing`（运行态）。

`state.trash`：`{ items: [{id, kind, title, thumbUrl, deletedAt, payload}], nextItemId }`，上限 50 条 FIFO。`kind`: `node`（整节点快照）/ `timeline-clips` / `timeline-clear`。节点快照 payload 含：节点序列化数据、7 类连线子集、被连带删除的时间轴片段、分组归属、**邻居节点字段补丁**（删除时被清掉的首尾帧/参考图/音色/水印输入原值，恢复时回填）。

## 三、文件清单

| 文件 | 角色 |
|---|---|
| `web/js/timeline.js` | 数据层：v2 迁移 `migrateTimelineToV2()`、放置算法（`resolveClipPlacement`/`nudgeUntilFree`/`placeClipAtTimelineEnd`）、渲染入口分支、导出收集带 `timeline_start` |
| `web/js/timeline_tracks.js` | 渲染与交互模块（`window.TimelineTracks`）：多轨渲染、拖拽 ghost、裁剪热区、分割、右键菜单、播放头、播放引擎（定时器 + 音频池）、磁吸指示线、分镜归属跟随落点、缩放、撤销入口、快捷键（S/空格/Delete/Esc） |
| `web/js/timeline_trash.js` | 垃圾桶模块：入桶/恢复/彻底删除/弹窗/角标/撤销浮条、序列化与恢复 |
| `web/css/timeline_tracks.css` | v2 时间轴 + 垃圾桶样式（`tt-` 前缀，主题变量与旧版一致） |
| `web/video_workflow.html` | 时间轴面板改为预览窗+多轨容器；垃圾桶入口（时间轴 header + 节点管理旁 `trashEntryBtn`） |
| `web/js/state.js` | `state.trash` 与 timeline v2 字段默认值 |
| `web/js/workflow.js` | `serializeWorkflow` 输出 `timeline.version/trackCount/zoom` + `trash`；`restoreWorkflow` 恢复两者并执行 v2 迁移 |
| `web/js/canvas.js` | `removeNode` 首行调用 `pushNodeDeletionToTrash` |
| `web/js/events.js` | 时间轴新工具栏按钮绑定；Delete 键优先走 v2 多选删除；清空时间轴先入垃圾桶 |
| `server.py` | `_export_timeline_absolute_mode()`：`timeline_start` 绝对布局导出分支 |

## 四、关键行为

### 旧数据自动迁移
加载工作流（`restoreWorkflow`）时，若 clip 缺 `start` 字段，`migrateTimelineToV2()` 按旧柱子渲染完全相同的算法（柱子按 自由柱→scriptId→shotNumber 排序累加，柱内按 order）一次性换算绝对位置，全部落到 track 0。迁移幂等，已迁移则直接返回。

### 放置与防重叠
- 「加入时间轴」：从播放头起找第一个空闲轨道；全忙回退 track 0 向右平移（`nudgeUntilFree`）。
- 拖拽落点：磁吸（视频 8px / 音频 12px 阈值，候选=0/播放头/所有片段起止，命中显示 `.tt-snap-indicator` 指示线）→ 目标轨防重叠平移；拖到「＋添加轨道」存根自动加轨（≤6，存根点击也可直接加轨）。
- **分镜柱子归属跟随落点时间**：拖拽落位后按落点意图时间（nudge 防重叠平移之前）判定覆盖该位置的分镜柱子，自动把片段划入该柱（同步 pillarId 与柱内成员/order）；无柱子覆盖时保留原归属。跨柱拖拽无需再走旧的拖到柱子 drop 协议。
- 剪切对话框（✂）：左端裁剪确认后 `clip.start` 随 `startTime` 差值右移。

### 分镜柱子（剧本/幕/分镜场景）兼容性
- 剧本→分镜组→分镜链路下 `getPillarForNode` 追溯逻辑未动，「加入时间轴」仍按节点连接自动落入对应镜头柱；无连线的素材落自由柱。
- 柱子色带在每条轨道内按片段聚合渲染（同一柱子跨轨分别画带），点击色带跳转分镜节点保留。
- v2 布局下柱子只是视觉分区与导出兼容元数据，片段的实际时间位置由 `start` 决定，跨柱移动即改 `start`（归属自动跟随）。
- 导出：payload 同时携带 `timeline_start`（绝对模式生效）与 `pillarId`（旧数据回退路径兼容）。

### 播放预览
预览 `<video>` 单元素复用：活跃片段取轨号最大者，跨片段边界切源（同 url 不重复加载只 seek）；音频用 `<audio>` 池并行调度（漂移 >0.35s 重定位）。播放结束自动停在末尾。任何编辑操作（拖拽/裁剪/删除/分割）先暂停。

### 垃圾桶恢复语义
- 节点：走 `restoreNode` 注册表链重建 + 回放快照连线（端点缺失的连线丢弃）+ 重映射 id 恢复时间轴片段 + 回填邻居补丁 + 计数器对齐。恢复后自动聚焦节点。
- 片段：id 重映射防碰撞；原柱子已清则落 `__free__` 并追加时间轴末尾。
- 删除 toast 带「撤销」浮条（6s）；垃圾桶按钮带数量角标（时间轴 header + 画布右下角）。

### 导出兼容
`collectTimelineExportClips` 每片段携带 `timeline_start`（及 `track`）；后端 `export_timeline_draft` 检测到全部视频片段有 `timeline_start` → 绝对模式（`_export_timeline_absolute_mode`，同源多段各取自身 payload 时长，规避旧柱子分支按 url 首条匹配的串段问题）；否则旧柱子/经典逻辑零改动。

## 五、边界与已知限制

- 垃圾桶不覆盖「工作流列表页删除工作流」（`video_workflow` 表仍是硬删除）。
- 快照不含 File 对象（如 TTS 的 refAudioFile），恢复后引擎字段保留、需重新应用音色一次。
- 删除节点时若邻居节点在删除后又被编辑，恢复的邻居补丁会覆盖这些字段（以快照为准）。
- 视频轨/音频轨上限各 6；音频拖进视频轨（或反之）会被拒绝。
- 撤销按钮走工作流级快照回滚（与 Ctrl+Z 同一机制），会整体回退最近一步（画布+时间轴一起），非时间轴专属 undo 栈。
- 导出素材包（`/api/export_timeline_assets`）不涉及位置，未改动。
