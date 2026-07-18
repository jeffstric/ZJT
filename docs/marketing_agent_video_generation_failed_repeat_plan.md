# 营销助手「视频生成失败」反复输出 修复方案

> 状态：**待实施**（根因已定位，方案已定，代码尚未改动）
> 关联文件：`web/marketing_agent.html`、`server.py`
> 创建日期：2026-06-19
> 行号基准：当前 `develop_427` 分支（已含「会话隔离 / 轮询守卫」修复）；实施时以函数名 + 逻辑定位为准，行号仅作辅助。

---

## 一、背景与现象

营销助手（`web/marketing_agent.html`）中，视频生成任务**失败**后，前端会**反复追加**多条 `视频生成失败，请稍后重试。` 消息（i18n key `video_generation_failed`，见 `web/i18n/locales/zh-CN/marketing_agent.json:116`），而不是只显示一条。

实测表现为同一会话内连续冒出多条失败消息（例如 18:49 出现 1 条、18:50 密集 5 条、18:52 又 2 条），用户无需任何操作即「不停地输出」。

---

## 二、根因分析

**一句话**：失败消息的追加**不是幂等的**；失败后去重键被删除，导致任务被「恢复/重启」路径反复拉起，每次都重新检测到失败终态并再追加一条。

### 证据链

1. **后端对失败任务持续返回 FAILED 终态**（`server.py` `get_status`，约 1723-1725）
   ```python
   elif status == -1:  # Failed
       status_str = "FAILED"
       reason_payload = reason
   ```
   任务记录一旦为失败态（`status == -1`），每次 `GET /api/get-status/{ids}` 都稳定返回 `status="FAILED"`。→ 前端只要再轮询一次，就一定能检测到失败终态。

2. **失败时删除了去重键**（`pollAgentVideoStatus`，约 2657）
   ```js
   if (allDone) {
       shouldContinuePolling = false;
       if (interval) trackedClearInterval(interval);
       activeGenerationPollKeys.delete(pollKey);   // ← 删掉去重键
       ...
       const replaced = await replacePendingTask(...);
       if (!replaced) await appendMessageToBackend('assistant', finalContent, pollSessionId); // 追加
       await cleanPendingTasksFromHistory(...);
   }
   ```
   `activeGenerationPollKeys`（声明于约 875）正是 `handleVideoTaskSubmitted` 防止「重复启动轮询」的依据（约 2590 `if (activeGenerationPollKeys.has(pollKey)) return`）。删除后，去重失效。

3. **没有任何「该任务已处理过失败终态」的持久标记**
   失败分支追加完一条 `视频生成失败` 后，代码里没有任何地方记录「`project_ids` X 已经追加过失败结果」。

4. **任务恢复 / 重启路径会反复触发 `handleVideoTaskSubmitted`**
   - `handleStream` 的 `message` 分支（约 3228）：AI 流式回复的**每个 chunk** 都调 `maybeRecoverVideoTaskFromAssistantText(data.content)`，chunk 含「视频」+「项目ID」即调 `handleVideoTaskSubmitted`。
   - `recoverVideoTasksFromAssistantMessages`（约 1174，被 `selectSession` 约 3944 与页面 `onMounted` 约 4211 调用）：**每次切换会话、每次页面加载**都遍历全部 AI 消息，对含项目ID 的消息调 `maybeRecoverVideoTaskFromAssistantText`。
   - 这些路径调用时，由于第 2 步已把 `pollKey` 删除，去重检查通过 → **重新启动一个新轮询实例**。

5. **`hasGeneratedVideoResult` 拦不住重启**（约 1163）
   ```js
   if (msg?.role !== 'ai' || !content.includes('<video')) return false;
   ```
   它判断消息里有没有 `<video>` 标签（成功结果）。失败消息 `视频生成失败` 不含 `<video>`，所以一直返回 `false`，恢复逻辑照常重启轮询。

6. **重启的轮询立即检测失败并追加**：新实例首次 `checkStatus` 查 `get-status` → 返回 `FAILED`（第 1 步）→ `allDone` → 走失败分支 → **又追加一条新消息**。

### 结论

只要失败任务的 `project_ids` 出现在任何 AI 消息文本里，每次该文本被 `maybeRecover` 处理（流式 chunk / 切换会话 / 刷新），就重启一次轮询、追加一条 `视频生成失败`。这就是「不停地输出」的来源。18:50 一波 5 条、18:52 又 2 条，符合「AI 流式回复 / 切换会话触发 burst」的特征。

### 次要放大因素（并发）

单实例内，`checkStatus` 失败分支含 3 个串行 `await`（`replacePendingTask` / `appendMessageToBackend` / `cleanPendingTasksFromHistory`）。若 `get-status` 响应慢（> 10s 轮询间隔），`setInterval` 会在 `await` 期间 tick 出并发的 `checkStatus`，每个都追加一条；且首个 `checkStatus` 把 pending 行替换/清理后，后续并发 `checkStatus` 的 `replacePendingTask` 全部失败、全走 append fallback。（失败任务的 `get-status` 只查 DB、较快，故该并发路径为次要因素；幂等化后一并消除。）

> 注：图片任务（`pollAgentImageStatus` / `handleImageTaskSubmitted` / `image_generation_failed`）走完全相同的机制，存在同样的反复追加风险，应一并修复。

---

## 三、触发场景

- **Agent 模式**：AI 回复文本中含「视频 / 项目ID」时，流式 chunk 与切换会话都会重启轮询。走 `pollAgentVideoStatus`。
- **视频模式（直接发起）**：`sendVideoRequest` → `checkDirectGenerationStatus`；恢复走 `recoverPendingTasks`（约 3875），切换会话/刷新时对 `_isPendingTask` 消息重复处理。
- 两种模式都受影响；根因相同（终态处理非幂等 + 去重失效）。

---

## 四、修复方案：终态处理幂等化

**核心目标**：每个 `project_ids` 的成功 / 失败结果**只追加一次**，且失败后**不再被恢复路径重启轮询**。

### 4.1 新增「已终结任务」集合

在状态区（`activeGenerationPollKeys` 附近，约 875）新增：
```js
const terminalGenerationKeys = new Set();  // 已处理过终态(成功/失败)的任务 pollKey，防止重复追加 / 重启
```

### 4.2 三个检查点

**(A) `checkStatus` 终态分支（`pollAgentVideoStatus` / `pollAgentImageStatus` / `checkDirectGenerationStatus`）——追加前查重**
进入 `allDone`（或 `anyFailed && !anyRunning`）分支后，**先判断是否已终结**：
```js
if (allDone) {
    // 幂等：同一任务终态只处理一次
    if (terminalGenerationKeys.has(pollKey)) return;
    terminalGenerationKeys.add(pollKey);

    shouldContinuePolling = false;
    if (interval) trackedClearInterval(interval);
    activeGenerationPollKeys.delete(pollKey);
    ... // 原有：更新占位 / replacePendingTask / append fallback / cleanPending
}
```
> 效果：并发 `checkStatus` 中只有首个能走到 append，其余命中 `terminalGenerationKeys` 直接 return。

**(B) `handleVideoTaskSubmitted` / `handleImageTaskSubmitted` 入口——拒绝重启已终结任务**
在现有去重检查旁追加：
```js
const pollKey = getGenerationPollKey('video', project_ids, pollSessionId);
if (terminalGenerationKeys.has(pollKey)) return;   // 已失败/成功的任务，不再重启轮询
if (activeGenerationPollKeys.has(pollKey)) return;  // 原有去重
activeGenerationPollKeys.add(pollKey);
```
> 效果：流式 chunk / 切换会话触发的 `maybeRecover` 不再为已终结任务重启轮询。

**(C) `clearAllTaskIntervals`（约 893）——切换会话时重置**
```js
function clearAllTaskIntervals() {
    activeIntervals.forEach(id => clearInterval(id));
    activeIntervals.clear();
    taskErrorCounts.clear();
    activeGenerationPollKeys.clear();
    directGenerationTasks.clear();
    terminalGenerationKeys.clear();   // 新增：切会话重置，允许新会话的同 project_ids 正常处理
}
```

### 4.3 同步覆盖两条路径

- **Agent 模式**：`pollAgentVideoStatus`（约 2613）、`pollAgentImageStatus`、`handleVideoTaskSubmitted`（约 2584）、`handleImageTaskSubmitted`（约 2463）。
- **直接发起模式**：`checkDirectGenerationStatus`（约 2297）的失败/成功分支同样加 (A) 幂等检查（其 `pollKey` 已存在于 `task.pollKey`，见 `createDirectGenerationTask` 约 947）。
- **`recoverPendingTasks`（约 3875）**：在「任务已完成」分支追加前，同样用 `terminalGenerationKeys` 查重（用 `getGenerationPollKey(msg._taskType, msg._projectIds, sessionId)` 构造 key），避免刷新/切换反复追加。

### 4.4 设计要点 / 边界

- `project_ids` 是任务的天然唯一键，一个 `project_ids` 对应一次生成，不会出现「同一 project_ids 被合法地二次生成」的情况，因此「已终结」标记是安全的。
- 标记随会话切换清空（4.2 C），不会跨会话误拦。
- 不改 `hasGeneratedVideoResult` 的语义（它仍用于「已有 `<video>` 成功结果则不恢复」），幂等集合是更底层的兜底。

---

## 五、涉及文件与改动点

| 文件 | 位置（当前约） | 改动 |
|------|------|------|
| `web/marketing_agent.html` | 约 875 状态区 | 新增 `terminalGenerationKeys = new Set()` |
| 同上 | 约 893 `clearAllTaskIntervals` | 清空 `terminalGenerationKeys` |
| 同上 | `pollAgentVideoStatus` 约 2654、`pollAgentImageStatus` 同构 | 终态分支追加前查重 + 写入集合 |
| 同上 | `checkDirectGenerationStatus` 约 2339（`anyFailed` 分支）及成功分支 | 同上 |
| 同上 | `handleVideoTaskSubmitted` 约 2590、`handleImageTaskSubmitted` 约 2468 | 入口处拒绝已终结任务 |
| 同上 | `recoverPendingTasks` 约 3884 | 「已完成」追加前查重 |
| `docs/marketing_agent.md` | 「任务状态轮询」「任务恢复机制」小节 | 补「终态处理幂等化」说明（CLAUDE.md 规则 2） |

---

## 六、测试方案

### 新增测试 `tests/js/test_marketing_agent_terminal_result_idempotency.js`

沿用现有 `html.slice(funcStart, funcEnd)` + `includes` 字符串断言风格（参考 `test_marketing_agent_direct_generation_isolation.js`）。断言：
1. 存在 `const terminalGenerationKeys = new Set()`。
2. `clearAllTaskIntervals` 函数体含 `terminalGenerationKeys.clear()`。
3. `pollAgentVideoStatus` / `pollAgentImageStatus` / `checkDirectGenerationStatus` 的终态分支含 `terminalGenerationKeys.has(` 与 `terminalGenerationKeys.add(`。
4. `handleVideoTaskSubmitted` / `handleImageTaskSubmitted` 含 `terminalGenerationKeys.has(pollKey)` 守卫。
5. `recoverPendingTasks` 含 `terminalGenerationKeys` 查重。

### 回归保护

- `test_marketing_agent_direct_generation_isolation.js`、`test_marketing_agent_image_poll_recovery.js`、`test_marketing_agent_cross_session_polling_isolation.js`、`test_marketing_agent_verification_session_restore.js` 应继续通过（本次只新增守卫，不改变既有 session 绑定/replacePending 逻辑）。

---

## 七、验证步骤

1. **JS 单测**：`node tests/js/test_marketing_agent_terminal_result_idempotency.js` 及上述回归测试，全部 `passed`。
2. **浏览器端到端**（人工）：
   - 构造一个会**失败**的视频生成任务（Agent 模式 / 视频模式各一次）。
   - 任务失败后，确认只出现**一条** `视频生成失败`，不再持续冒泡。
   - 切换到其他会话再切回，确认**不会**再追加新的失败消息（历史中仍是那条）。
   - 刷新页面，确认不会因恢复逻辑再追加。
   - 图片任务同理验证。
3. **正常成功路径回归**：成功的视频/图片任务仍只渲染一次结果，不因幂等集合漏渲染。

---

## 八、风险与备注

- **风险低**：改动是对齐现有 `activeGenerationPollKeys` 范式的「再加一层幂等集合」，不重构数据结构。
- **与上一个修复的关系**：本 bug 与「跨对话串台」（已修，session 守卫）**独立**。session 守卫解决「结果写到错误的对话」，本方案解决「同一对话内反复追加」。两者互补。
- **待确认**：实施前可顺带核实——失败任务的 `replacePendingTask` 为何常走 fallback append（后端 `replace-pending-task` 是否总能匹配到 pending 行？若匹配可靠，并发场景下的多 append 会减少，但幂等集合仍是必要的兜底）。
