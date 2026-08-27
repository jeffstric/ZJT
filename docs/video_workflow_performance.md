# video_workflow 节点编辑器性能优化方案

> 背景：`web/video_workflow.html` 节点数量增多后浏览器崩溃。本文档记录根因分析与本次优化内容（2026-08，自动保存相关脚本版本参数 `?v=__VERSION__`（跟随版本发布））。

## 一、根因分析

崩溃是 **CPU 主线程打满** 与 **内存耗尽** 的叠加，按影响排序：

| # | 问题 | 位置（优化前） | 影响 |
|---|------|--------------|------|
| 1 | mousemove 每次触发全量销毁重建 6 类 SVG 连线：全删全建 + 每线重绑监听器 + 每线 2~4 次 `getBoundingClientRect` + `updateCanvasSize()` 遍历全部节点读 `offsetWidth`（layout thrashing），无任何 rAF 节流 | `events.js` mousemove（平移/拖拽/放置/拉线 4 个分支） | 拖拽/平移时主线程打满，页面无响应 |
| 2 | 每个视频节点完成后 `loop=true` 自动循环播放，N 个视频节点 = N 条并行解码管线，解码缓冲不释放 | `node_base.js setupVideoThumbnail`、`workflow.js updateNodePreview/restoreNode`、`image_to_video_node.js` 等 | 内存耗尽崩溃 |
| 3 | undo 历史栈保存 50 份全量 JSON 字符串快照，`data:` base64 大字符串未被完全剔除，内存被放大数十倍 | `workflow.js captureHistorySnapshot` / `serializeWorkflow`、`state.js historyLimit` | 内存耗尽崩溃 |
| 4 | `safeAutoSave` 无防抖，全页 100+ 处调用，每次 = 2 次全量序列化 + PUT 全量上传 | `node_base.js safeAutoSave` | CPU + 网络 |
| 5 | 无虚拟化：每节点 100+ DOM 元素常驻渲染；minimap 每次交互 `innerHTML` 全量重建并逐节点读 `offsetWidth`；轮询每 60s 对所有分镜节点执行 3 组 `innerHTML` 重建 | `canvas.js renderMinimap`、`workflow.js pollWorkflowNodeStatus` | 周期性卡顿 |

## 二、优化内容

### 1. 连线渲染 rAF 调度（`connection_base.js`、`events.js`、`canvas.js`）

- 新增 `scheduleConnectionsRender(opts)`：requestAnimationFrame 合帧，同一帧内多次请求只做一次全量渲染；`flushConnectionsRender()` 取消挂起调度并立即渲染（拖拽结束、删除连线等同步场景）。
- `renderAllConnections(opts)` / `renderConnections(tempLine, skipSizeUpdate)` 支持 `skipSizeUpdate`：拖拽期间跳过 `updateCanvasSize`（内部遍历全部节点读 `offsetWidth`），mouseup 时统一补偿。
- **平移画布不再重画连线**：连线 SVG 与节点同在 `canvasWorld` 内，随 CSS transform 整体移动，端口世界坐标换算 `(rect - containerRect - pan) / zoom` 数学上恒等，重画是多余的。改为只调用 `updateSelectedConnDeleteBtnPos()` 重新定位挂在屏幕坐标系上的删除按钮。
- **拉线预览改用常驻 path**：新增 `updateTempConnLine(line)`，只更新 `d` 属性，替代原先每帧全删全建普通连线的 `renderConnections(tempLine)`；拉线时节点未移动，紧随其后的全量 `renderAllConnections()` 属冗余调用，已删除。
- 滚轮缩放 `setZoom` 与小地图 `renderMinimap` 均走 rAF 合帧（`scheduleMinimapRender`）。
- 节点选中后 250ms 定时的全量重渲染改为调度版（合帧，行为不变）。

### 2. 视频缩略图：封面帧 + 悬停播放（`node_base.js` 及各触点）

- `setupVideoThumbnail(thumbVideo, url)` 重写：`preload='metadata'`，metadata 就绪后 seek 到第一帧（0.1s）作为封面；移除 `loop=true` 与自动 `play()`。
- 新增 `attachVideoHoverPreview(thumbVideo)`：在节点元素上挂 mouseenter/mouseleave——悬停播放、移开暂停并回到封面帧；监听器随节点子树销毁回收。手动播放状态（`thumbVideo.dataset.manualPlay === '1'`，由视频节点的播放按钮维护）不受移开暂停影响。
- 触点收敛（全部改调统一函数）：`workflow.js updateNodePreview` / `restoreNode`（工作流重载后封面帧复原）、`nodes.js`、`image_to_video_node.js`、`video_node.js`（本地上传 blob URL 原样透传）。

### 3. 快照与保存瘦身（`workflow.js`、`state.js`、`node_base.js`、`auto_save_state.js`）

- `serializeWorkflow` 新增 `stripLargeDataUrls()`：深度遍历剔除超过 4KB 的 `data:` base64 大字符串（不可变实现，不污染运行态 `state`）；`preview/startPreview/endPreview` 字段按显式映射（`preview→url`、`startPreview→startUrl`、`endPreview→endUrl`，注意 `preview` 为小写，不能用正则推导）优先用已上传 `url` 回填，未命中映射或无对应 `url` 时一律置空——绝不能把原始 base64 写回，否则优化失效。**注意**：提取帧节点本地选择的大视频 base64 不再持久化（原行为会把几十 MB 字符串写入 DB 与 undo 快照）。
- `state.historyLimit` 50 → 20：历史快照为全量 JSON 字符串，约束 undo 深度换内存。
- `safeAutoSave` 拆分「快照」与「上传」两条时间线：历史快照（`captureHistorySnapshot`，内部有去重）在每次调用时**立即**捕获，保证 1.5s 内多次操作各有独立撤销点（防抖延迟快照会导致 Ctrl+Z 一次撤销多操作）；PUT 上传仍按 1500ms 防抖（`AUTO_SAVE_DEBOUNCE_MS`，`skipHistory: true`），高频调用点无需改动。
- `flushAutoSave()`：取消挂起防抖并立即落盘（先补快照再 PUT），用于删除节点等需要立即持久化的场景（`canvas.js removeNode`）。
- `beforeunload` 补发改为**基于保存状态机的三分支决策**（`auto_save_state.js` 的 `planUnloadSend`），不再只检查防抖定时器是否存在（定时器触发后为 null 但请求可能仍在途，只查定时器会漏发）：
  - 状态机：`version`（每次 `markDirty` 自增）/ `confirmedVersion`（服务器已确认的最高版本）/ `inFlight`（当前保存，含 `requestStarted` 区分"等待 IDB" 与"网络 PUT 已启动"）。只有"发送后无新修改"（`sentVersion === version`）的成功响应才推进 `confirmedVersion`；被新 `beginSend` 取代的旧请求的迟到 ack 因版本号不匹配自动失效。
  - 分支 1（定时器待触发：dirty、无在途）→ 补发，body 可 keepalive 时用 `keepalive: true`。
  - 分支 2（请求正在发送）→ 在途即最新且为 keepalive 请求则无需补发（卸载后浏览器继续发送）；在途即最新但为普通 fetch 则中止并**升级 keepalive** 重发（严格更优）；在途已过期（发送后又修改）则中止并用最新 payload 重发；超限（>59KB）时无法升级，让原请求尽力发送。
  - 分支 3（请求体超限）→ keepalive 有 64KiB 硬上限（MDN `RequestInit.keepalive`），超限时（`KEEPALIVE_BODY_MAX_BYTES`，按 `Blob.size` 实际 UTF-8 字节数判定）回退普通 fetch（best effort），并由下述 IndexedDB 恢复记录提供 best-effort 恢复。
  - 持久化阶段（`beginSend` 已登记、但 `requestStarted === false`）关页 → 不能当作网络请求在途；无论 body 大小都中止原 controller 并立即补发最新 payload。
  - keepalive 替代不了 sendBeacon 的原因不变：sendBeacon 无法带 `X-User-Id`/`Authorization` 头，端点依赖 `X-User-Id`，故不用。
- **并发自动保存防乱序**：`autoSaveWorkflow` 发起新 PUT 前先 `abortInFlight()` 中止本页旧在途请求，降低过期 payload 晚到的概率。`endSend` 返回布尔（仅"该请求是最新发送且成功"为 true），**清除恢复记录只在返回 true 时执行**。注意：`AbortController` 无法撤回已到达服务端的 PUT，严格防止跨标签页/服务端乱序覆盖仍需后端 revision/CAS。
- **dirty 跟踪覆盖所有保存入口**：`autoSaveWorkflow` 在守卫（workflowId/就绪检查）后统一 `markDirty()`，undo/redo、shot_group 模型切换/人脸选项等直接调用 `autoSaveWorkflow` 的路径（不经过 `safeAutoSave`）同样被关页补发逻辑捕获。
- **手动保存与恢复状态机统一**：手动保存会取消未触发的防抖任务、中止本页旧自动保存、用手动 body 覆盖恢复快照，并在服务器确认后条件清理，避免下次打开时重放旧自动保存覆盖手动结果。
- **大工作流（>59KB）IndexedDB 恢复机制**：keepalive 超限回退普通 fetch 后请求不保证在卸载后送达。常规自动保存会在 PUT 发送前 `await WorkflowRecovery.saveSnapshot(...)`；服务器确认最新版本后再条件清理。下次打开页面时，`maybeRecoverPendingAutoSave` 重放当前用户/工作流的未确认记录（原样 re-PUT），成功后清记录、提示并重新加载工作流。
  - **卸载时序**：页面初始化时预热 IDB 连接。`beforeunload` 只序列化一次 body，`startUnloadSend` 同步尝试 `saveSnapshotSync` 后直接调用 `fetch`，确保网络请求在任何 `await` 之前启动。若 IDB 连接尚未就绪，则在 fetch 已启动后异步补写。`saveSnapshotSync === true` **仅表示 put 已入队，不表示事务已持久化**。
  - **分区与条件清理**：IndexedDB key 使用无碰撞的 `[userId, workflowId]` JSON 编码；身份或 `snapshotId` 缺失时 fail-closed，拒绝写入/读取/重放。每次写入带跨标签页唯一 `snapshotId`，以及页面级 `writerId + writerSequence`；`clearSnapshot` 在同一 readwrite 事务中 `get → 比对 snapshotId/version → delete`。新 PUT 已确认但本次快照写入临时失败时，`clearConfirmedSnapshot` 只可额外清理**同 writer 且序号严格更小**的残留记录。不同标签页不用时间戳比较先后，避免删除另一页较早创建但尚未送达的独立编辑。v1 的全局 `latest` 记录只在身份完整时迁移，否则删除。
  - **恢复重载有界**：重放成功后只做一次跳过恢复检查的 UI reload。若条件删除返回 false（另一标签页已写入新 token 或 IDB 删除失败），保留记录供后续页面处理，不在当前调用链无限 `GET → PUT → reload`。
  - 同一用户/工作流的多标签页共享一个 key（最后一次 IDB 写入胜出）；`snapshotId` 解决的是迟到确认误清问题，不是服务端 PUT 乱序冲突。无 IndexedDB 环境静默降级为 no-op，keepalive 路径不受影响。

### 4. 节点尺寸缓存（`node_base.js`、`canvas.js`、`workflow_layout.js`）

- 新增 `getNodeSize(node)`：优先读 `el._cachedSize`，miss 或脏时读 `offsetWidth/offsetHeight` 回填。
- 失效机制：单一全局 `ResizeObserver` 维护 `el._sizeDirty` 脏标记；`MutationObserver` 监听画布 childList，新挂载节点自动纳入观察（覆盖所有节点创建路径，无需各创建函数接入）。不支持 `ResizeObserver` 的环境自动降级为直读。
- 替换全量读取点：`updateCanvasSize`、`renderMinimap`（两轮循环复用一次查询）、`workflow_layout.js getNodeDimensions`（自动布局/碰撞检测的高频读取）。

### 5. 轮询增量更新（`workflow.js pollWorkflowNodeStatus`）

- 对世界数据（characters/props/locations）做 JSON 指纹比对（`state._lastWorldFingerprint`），指纹未变且无节点状态更新时，跳过对所有分镜节点 `updateReferences()` 的调用（原实现每 60s 触发每节点 3 组 innerHTML 重建）。
- 节点恢复路径（`restoreNode`）不受影响，工作流重载/undo 后引用显示照常全量刷新。

## 三、涉及文件

`web/js/connection_base.js`、`events.js`、`canvas.js`、`nodes.js`、`workflow.js`、`node_base.js`、`state.js`、`workflow_layout.js`、`video_node.js`、`image_to_video_node.js`、`auto_save_state.js`；`web/video_workflow.html`（自动保存相关脚本版本参数 `?v=__VERSION__`（跟随版本发布））。

## 四、验证情况

- `node --check` 全部改动文件语法通过。
- `npx vitest run`：31 个测试文件、291 个用例全部通过。其中 `web/tests/auto_save_unload.test.js` 34 个用例，覆盖关页三分支、IDB 持久化阶段的大 body 补发、dispatcher → unload → fetch 同步接线、用户/工作流分区、snapshotId/version/writer 条件清理、v1 `latest` 迁移、IDB blocked 后 fail-open/重试及无 IDB 降级。
- 此前 `?v=perf3` 基线曾完成真实服务器手动 E2E（Playwright 9/9）：定时器待触发关页补发、在途请求升级 keepalive、>59KB 恢复重放、跨工作流门控及 undo 直接保存。该 9/9 仅作历史基线，本轮改动未重跑真实服务器 E2E，不计入上述当前验证结果。
  - Playwright 限制说明：其 CDP 网络拦截层在 `page.close()` 时随 renderer 销毁，keepalive 请求不保证放行（真实浏览器中 keepalive 为浏览器原生行为）。故 T1/T2 用页内 `dispatchEvent('beforeunload')` 触发同一 handler 验证状态机决策与真实落库，已用服务器访问日志核对 PUT 时序。
  - 节点重载（restore）只复原类型化字段，自定义 data 字段重载后丢失——跨页重载场景的断言须用真实字段。
- 手动回归清单（建议在大工作流上执行）：
  - 拖拽（单个/批量框选）、平移、滚轮缩放：连线跟随、帧率
  - 拉线创建/删除连线（虚线预览、端口高亮、选中删除按钮位置）
  - undo/redo（1.5s 内连续多次操作，逐次 Ctrl+Z 应每次只回退一步）；自动保存（快照即时、PUT 防抖 1.5s；手动保存按钮不受影响）；关页前最后 1.5s 内的修改会在卸载同步调用栈内启动补发
  - 关页三分支：修改后立即关页（定时器未触发）/ 修改后等 PUT 在途时关页（DevTools 慢速网络观察）/ 大工作流（>59KB）关页——前两者应在 Network 面板看到 keepalive PUT；大工作流若本次未送达，下次打开页面应出现「已恢复上次未送达的自动保存」toast 且内容正确
  - 视频节点：生成完成后显示封面帧、悬停播放、播放按钮手动模式、上传本地视频
  - **工作流重载后节点与视频封面帧复原**
  - 轮询期间世界数据变化后引用标签更新（改世界角色图后 60s 内刷新）
- 性能验证建议：构造 200+ 节点、100+ 连线、20 个视频节点的测试工作流，用 DevTools Performance/Memory 观察拖拽帧率与 10 分钟操作的堆内存曲线。

## 五、后续可选优化（本次未做）

- **大工作流关页的残余缺口（有意保留）**：>59KB 的关页 PUT 无法 keepalive，只能普通 fetch + IndexedDB best-effort 恢复。卸载时 `saveSnapshotSync` 返回 true 只说明 put 已进入事务队列，页面/浏览器迅速销毁时仍不能承诺持久化成功。若未来需彻底消除，可在 dirty 阶段提前异步落盘，或改为增量 PATCH / 操作日志（按节点 diff 上报，天然小报文可 keepalive）。

- **连线 DOM 复用**：`renderConnections` 仍为全删全建模式（已通过 rAF 合帧大幅降频）；可进一步改为 path 元素池 diff，端点不变时只更新 `d` 属性。
- **视口外节点虚拟化**：`content-visibility` / IntersectionObserver 对视口外节点做渲染裁剪与媒体卸载，适合节点规模长期上几百个的场景。
- **shot_frame 数据去重**：`videoPrompt`（JSON 字符串）、`videoPromptText`、`shotJson` 三份重复大文本可考虑去重（需先确认恢复逻辑的字段消费关系）。
- 端口相对偏移缓存（消除拖拽连线时的 `getBoundingClientRect`）——收益/风险比一般，暂缓。
