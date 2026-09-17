# 生成任务时间轴（video_workflow / storyboard）

## 功能概述

video_workflow.html 与 storyboard.html 中所有「生成中」的图片/视频任务，都可以点击「状态」按钮打开**任务事件时间轴弹窗**，查看任务从提交到完成的每个事件（提交上游、状态轮询、下载、CDN 上传、重试等），与 index.html 历史记录里的时间轴同源同体验。

- video_workflow：结果节点（图片节点 / 视频节点）生成中显示占位/状态行 + 「状态」按钮；完成后按钮保留，可回看完整时间轴。
- storyboard：候选区（分镜图候选 / 视频候选）的生成中、失败占位卡上有「状态」按钮；已完成候选卡 hover 显示左下角「状态」角标。
- 弹窗内任务未到终态（状态 0/1/3/4/5/6）时每 5 秒自动刷新；终态（2 成功 / -1 失败）停止。

## 数据链路（全部复用既有链路，无新表）

```
提交生成（POST /api/image-edit | /api/text-to-image | /api/ai-app-run(-image)）
  → ai_tools 记录（id 即前端 project_id）
  → task/visual_task.py 调度执行，逐事件写 ai_tools_log（append-only）
  → 前端 AiToolTimeline.open(ai_tool_id)
      → GET /api/ai-tools/{id}/timeline（server.py，管理员任意 / 非管理员仅本人）
      → 渲染事件列表（时间/事件类型/消息/耗时/可展开 detail JSON）
```

事件类型（`model/ai_tools_log.py::AIToolsLogEvent`）：record_created / task_started / slot_delayed / implementation_selected / submitted / status_check / upstream_succeeded / upstream_failed / download_started / download_completed / cdn_uploaded / retry_scheduled / max_retry_exceeded / task_completed / exception / pipeline_step。

## 公共模块

| 文件 | 说明 |
|------|------|
| `web/js/ai_tool_timeline.js` | 弹窗 + 节点辅助（普通 script，挂 `window.AiToolTimeline`，两页共用） |
| `web/css/ai_tool_timeline.css` | 弹窗与按钮样式（依赖页面 `--bg/--text/--muted/--border` 变量，自动适配暗色主题） |
| `web/i18n/locales/{zh-CN,en}/common.json` | 新增 `task_timeline` / `timeline_btn_status` / `timeline_*` 等 key（两页均加载 common 命名空间） |

### window.AiToolTimeline API

| 方法 | 说明 |
|------|------|
| `open(taskIds)` | 打开弹窗；支持 `number \| number[]`，多任务时顶部 `#id` tab 切换 |
| `close()` | 关闭弹窗 |
| `markNodeGenerating(nodeId)` | video_workflow：结果节点绑定 project_id 后显示「生成中」提示 + 按钮（image→占位 / video→状态行） |
| `settleNodeResult(node)` | url 到位后收尾（image 隐藏占位 / video 状态行 ✓ 生成成功） |
| `failNode(nodeId, message)` | 失败态展示（占位/状态行 ✗ 原因，按钮保留） |

按钮（`.ai-task-timeline-btn`）点击由**捕获阶段**全局委托处理并 `stopPropagation`，因此不会误触发候选卡选中、画布节点选中等交互。任务 id 解析优先级：`data-task-ids` 属性（storyboard 候选卡）→ 回溯 `.node[data-node-id]` 查全局 `state.nodes` 的 `projectIds / project_id / aiToolsId`（video_workflow）。

## video_workflow 接入点

所有图片生成入口都创建 image 结果节点、视频生成入口都创建 video 结果节点，因此按钮统一落在两个结果节点模板上：

- `web/js/video_node.js`：`.video-status-field` 状态行内加「状态」按钮（状态行显示即出现）。
- `web/js/image_node.js`：预览区加 `.image-generating-placeholder`「生成中」占位（含按钮）。

调用时机：

| 时机 | 位置 |
|------|------|
| 提交后绑定 project_id | image_node.js、shot_frame_generator.js、shot_frame_video_generator.js、image_to_video_node.js、camera_control_node.js、panorama_node.js、digital_human_node.js、nodes.js（宫格 + 分镜组视频）、script_node.js（三处宫格）→ `AiToolTimeline.markNodeGenerating(nodeId)` |
| 单轮完成后 url 到位 | 各入口 onComplete 更新节点处 + `workflow.js updateNodePreview` → `settleNodeResult(node)` |
| 失败 | `workflow.js updateNodeErrorDisplay` → `failNode(node.id, message)`（红色横幅保留，状态行/占位同步失败态） |
| 工作流重载恢复 | `workflow.js createVideoNodeWithData / createImageNodeWithData`：`project_id && !url` 时恢复占位/状态行（失败优先恢复失败态），轮询恢复由既有 `pollWorkflowNodeStatus` 驱动，完成后走 `updateNodePreview` 收尾 |

## storyboard 接入点

- 后端 `api/storyboard.py`：
  - `_asset_task_info`（选中资产行）与 `_generating_row_task_info`（生成中行）返回值新增 `ai_tool_id` 字段；`GET /scene/{id}/task-status` 透出。
  - `GET /scene/{id}/assets` 本就返回 `ai_tool_id`（`StoryboardSceneAssetModel.to_dict`），无需改动。
- 前端：
  - `web/js/storyboard/scene_candidates.js`：`mapSceneAssetCandidates` 候选映射新增 `aiToolId`。
  - `web/js/storyboard/polling.js`：`upsertSceneCandidateFromTask` / `upsertGeneratingCandidate` 回填 `aiToolId`；`scene.taskStatus` 增加 `first_frame_ai_tool_id` / `video_ai_tool_id`（候选列表未加载时的回退占位卡也可查看）。
  - `web/js/storyboard/render.js`：`renderCandidatePlaceholder` 生成中/失败占位卡内渲染「状态」按钮；已完成候选卡 hover 显示 `candidate-status-button` 角标（无 `aiToolId` 的上传资产不显示）。

## 安全说明

- 弹窗内所有动态文本（message / detail JSON / 时间）一律 DOM API + `textContent` 渲染，不拼接 HTML（`detail` 可含上游响应原文）。
- 候选卡按钮的 `data-task-ids` 经 `escapeHtml` 转义（`web/js/escape.js` 统一实现）。
- 接口鉴权与归属校验沿用 `GET /api/ai-tools/{id}/timeline`（`ai_tools:view_history`，非本人 404）。
