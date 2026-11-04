# 排队任务取消（video_workflow）设计文档

> 分支：develop_f997 ｜ 2026-10 ｜ 需求：video_workflow.html 中排队中的任务允许取消，
> **绝不出现「已取消的任务又被调用上游接口」**。

## 1. 背景

视频/图片生成任务提交后并非立即调用上游供应商接口，而是先进入排队阶段
（调度队列 / 同步进程池 / 预处理流水线）。此前前端只显示「生成中...」，
用户无法中止误提交或不想再等的排队任务，只能等待其被调度执行并消耗算力。

## 2. 状态扩展（`config/constant.py`）

| 表 | 新状态 | 值 | 含义 |
|---|---|---|---|
| ai_tools | `AI_TOOL_STATUS_CANCELLED` | -2 | 用户取消（排队阶段终态） |
| tasks | `TASK_STATUS_CANCELLED` | -2 | 同上（双表同步） |
| ai_tool_pipeline_steps | `PipelineStepStatus.CANCELLED` | -3 | 任务取消时未执行步骤连带取消 |

可取消状态集合（尚未调用上游提交接口、未产生上游成本）：

```python
AI_TOOL_CANCELLABLE_STATUSES = (PENDING(0), SYNC_QUEUED(3), WAITING_PARAM_PREPARE(4))
```

`PROCESSING(1)`（已提交上游或提交中）、`WAITING_BEFORE_FINISH(5)`（失败重试中）、
终态（2/-1/6）均**不可取消**。

无表结构变更（status 为 tinyint 值域扩展），不需要 alembic 迁移。

## 3. 核心互斥：条件更新（CAS）竞争

「取消」与「调度器提交上游」在 **ai_tools 同一行** 上以条件 UPDATE 竞争，
MySQL 行锁保证串行、先到先得：

```
取消接口:    UPDATE ai_tools SET status=-2 WHERE id=? AND status IN (0,3,4)
调度器闸门:  UPDATE ai_tools SET status=1  WHERE id=? AND status=0      （提交上游前）
同步池闸门:  UPDATE ai_tools SET status=1  WHERE id=? AND status=3      （worker 执行前）
步骤分发闸门: UPDATE ai_tool_pipeline_steps SET status=1 WHERE id=? AND status=0
取消连带:    UPDATE ai_tool_pipeline_steps SET status=-3 WHERE ai_tool_id=? AND status=0
```

竞争矩阵（任一时序下均安全）：

| 先到 \ 后到 | 取消先落库 | 调度器先抢占 |
|---|---|---|
| 取消接口 | — | affected=0 → **409 拒绝取消**（任务已开始生成） |
| 调度器 CAS | affected=0 → 记 `cancel_guard_rejected` 日志、**放弃调用上游** | — |

即：**取消成功 ⇒ 之后任何提交闸门必然 affected=0 ⇒ 绝不调用上游接口**；
反之任务一旦开始提交，取消立即被拒，用户得到明确提示。双向互斥，无竞态窗口。

### 三处上游调用闸门

1. **异步提交**（`task/visual_task.py::_submit_new_task`）：
   - param_prepare 分支前 CAS `0→4`；
   - sync_mode 分流前 CAS `0→3`（入池失败回滚 `3→0`）；
   - 调 `driver.submit_task`（上游 HTTP）前 CAS `0→1`——核心闸门。
   - 提交失败/拥堵重试回滚 `1→0`（条件更新，不覆盖期间发生的取消）。
2. **同步池执行**（`task/sync_task_executor.py::_execute_sync_task`）：
   worker 从池队列取出任务后、创建 driver 前 CAS `3→1`；失败直接返回，
   不调接口、不写终态（取消接口已落终态+退款）。
3. **流水线步骤分发**（`task/pipeline_processor.py::dispatch_step`）：
   ai_tool 已取消 → 步骤标记 CANCELLED 跳过；否则步骤行 CAS `PENDING→PROCESSING`
   （与取消连带的 `PENDING→CANCELLED` 互斥）。

### 终态防覆盖

- `_handle_task_failure`（visual_task）：ai_tool 已 CANCELLED → 跳过（不覆盖为 FAILED、
  不触发企业版 before_finish 重试——重试会把任务推回 PENDING 导致取消后被重新提交）。
- `SyncTaskExecutor._handle_task_result`：CANCELLED 结果（worker 抢占失败）不写库。
- `_check_pipeline_stage` / `_check_ai_tool_stage_completion`：param_prepare 完成推进回
  PENDING 用 CAS `4→0`；已取消保持 CANCELLED。
- `process_generate_video`：状态分发遇 CANCELLED 时同步 tasks 表（防双表不同步空转）。
- `process_task_with_retry` 的过期 / 超最大重试分支：FAILED 写入改用
  `AI_TOOL_ACTIVE_STATUSES` 条件更新——调度循环持有旧快照期间用户取消落库时，
  不会把 CANCELLED 覆盖成 FAILED；尾部卡死恢复同步识别 CANCELLED（tasks 5→-2）。

### RunningHub 槽位归还

调度循环持有任务旧快照期间用户取消落库时，本轮已领用的槽位不会再随任务生命
周期释放，会永久占用并发容量（真实数据库复现确认，见下节）。归还必须覆盖
**每一个「检出已取消」的调度路径**（幂等，无槽位记录时空操作）：

| 检出点 | 时序覆盖 |
|---|---|
| `process_generate_video` CANCELLED 分支 | 取消落在「领槽之后、分发取快照之前」（before_slot / after_slot 时序） |
| `_submit_new_task` 提交闸门被拦截（CAS affected=0） | 取消落在「取到 PENDING 快照后、闸门前」（after_fetch 时序） |
| 取消接口成功落库后（server.py） | 取消先于槽位领用发生（此时槽位尚不存在，为空操作兜底） |

## 4. 取消接口

`POST /api/ai-tool/{ai_tool_id}/cancel`（`server.py`，`@require_permission("video:view_status")`）

1. 属主校验（`request.state.user_id` vs `ai_tools.user_id`）；
2. CAS `IN(0,3,4) → CANCELLED`；affected=0 → 409「任务已开始生成或已结束，无法取消」；
3. tasks 表同步 CANCELLED；未执行 pipeline 步骤连带取消；
4. 幂等退款（`refund-{原扣费流水号}`，线程池执行避免阻塞事件循环）；
5. 写 `ai_tools_log`：`user_cancelled` / 调度侧 `cancel_guard_rejected`。

## 5. 状态查询细分

`GET /api/get-status/{id}`：`0/3/4 → "QUEUED"`、`-2 → "CANCELLED"`（带 reason），
其余不变。前端据此区分「排队中（可取消）」与「生成中（不可取消）」。

## 6. 前端（video_workflow.html 链路）

- `web/js/api.js`：新增 `cancelQueuedAiTask(id)`（POST + Authorization 头）；
  `checkVideoStatus` 全局状态纳入 `CANCELLED` 终态（`QUEUED` 视为未终态继续轮询）。
- `web/js/ai_tool_timeline.js`：
  - `markNodeGenerating` 时在 video 状态行 / image 占位区渲染「取消排队」按钮，
    并做一次远端状态同步（**工作流重载恢复**：QUEUED 保留按钮、RUNNING 隐藏、
    CANCELLED 直接标记终态）；
  - `markNodeCancelled`（节点标记「已取消（算力已退还）」+ `node.data.cancelled` 持久化）、
    `setNodeCancelVisible`；全局 click 委托处理 `.ai-task-cancel-btn`，
    confirm 后调取消接口，成功标记节点、失败（409 等）恢复按钮并 toast。
- `web/js/workflow.js::pollVideoStatus`：终态判断纳入 CANCELLED；每轮轮询按
  `task.project_id` 反查节点集中同步按钮可见性——所有 pollVideoStatus 消费方
  （图生视频/文生视频/数字人/全景/分镜/宫格等）自动获得取消能力，无需逐一改造。
- i18n：`web/i18n/locales/{zh-CN,en}/common.json` 新增 `ai_task_cancel_*` 等 7 个 key。
- 样式：`web/css/ai_tool_timeline.css` `.ai-task-cancel-btn`。
- storyboard 右侧「视频候选」与「分镜图候选」的生成占位卡复用同一取消接口：`web/js/storyboard/api.js` 的 `cancelAiToolTask`（POST + Authorization 头，token 不进 URL）。按钮类名是 `.candidate-task-cancel`（动作 `cancel-scene-task`），不要复用 `.ai-task-cancel-btn`（时间轴脚本的捕获监听只认画布节点，会吞掉故事板点击）。排队成功显示「已取消」并退算力；预处理在途为「取消中」；已开始生成为 409。取消标记（`state.sceneTaskCancelByToolId`）对图片 `first_frame` 与视频 `video` 的候选列表和 `taskStatus` 统一防护；宫格拆分共享同一 `ai_tool_id` 的多个图片候选一并标记。
- index.html 各工具页（AI视频/脚本/数字人/图生视频/图片编辑/视频增强/文生图）
  的历史记录状态映射补 `-2: 已取消`（灰色），取消任务在历史列表正确展示。

## 7. 已取消任务的算力

取消成功即幂等退款（优先按扣费流水原额退还）；此后任何失败/重试路径的退款
调用都会被 `is_already_refunded`（同退款流水号）拦截，不会重复退。

## 8. 真实数据库验证（本地复现）

复现工具：`scripts/repro_queued_cancel_slot.py`（确定性注入，不靠 sleep 撞运气）+
`scripts/bootstrap_slot_leak_schema.py`（独立 schema 建表，密码走环境变量）。
钩子在调度循环的三个精确时刻注入「用户取消」，模拟真实竞态时序：

| 注入时序 | 含义 |
|---|---|
| before_slot | 取消落在「调度器已取任务快照、尚未领槽位」（凭旧快照仍会领槽） |
| after_slot | 取消落在「槽位已领用、提交前」（原始泄漏窗口） |
| after_fetch | 取消落在「分发取到 PENDING 快照后、提交闸门前」 |

每次运行校验四项：ai_tools/tasks 终态 -2、`submitted` 事件为 0（取消后绝不调
上游）、project_id 为空、活跃槽位行（status=1）是否残留。

### 结果（本地 MySQL 8.0.41，max_concurrent_slots=3）

| 代码版本 | before_slot | after_slot | after_fetch | 容量影响 |
|---|---|---|---|---|
| ed40fac3（未修复*） | ❌ 泄漏 | ❌ 泄漏 | ❌ 泄漏 | 3 次取消后槽位 3/3 耗尽，第 4 个正常任务 `try_acquire_slot=False` |
| bbaa06a7（第一版修复*） | ❌ 泄漏 | ❌ 泄漏 | ✅ 已释放 | — |
| 当前（+CANCELLED 分支还槽） | ✅ 已释放 | ✅ 已释放 | ✅ 已释放 | 取消后槽位即时归还，容量不受影响 |

\* 两阶段均对 CAS 原语施加了同一份参数顺序热修，以隔离考察槽位行为（原语
bug 两版同在，见下节）。所有时序下「取消后不调上游」不变量均成立（submitted=0）。

### 事故复盘：CAS 原语参数错序（本次验证的最大收获）

首跑即异常：三种时序下取消全部落库失败。排查发现
`AIToolsModel.transition_status` / `PipelineStepModel.try_update_status` 的参数
顺序与 SQL 占位符顺序不一致——`WHERE id = %s AND status IN (...)` 中 id 在 IN
之前，而参数把 `record_id` 放在末尾，导致 `WHERE id` 绑定到 `from_statuses[0]`
（PENDING=0），**条件更新永远 0 行命中**。若未经此验证直接上线：

- 取消接口对一切排队任务返回 409（取消功能完全失效）；
- 调度器提交闸门 CAS 恒为 0 → 每个正常任务都被误判「已取消」而拒绝提交
  （视觉任务全量停摆）；
- 流水线步骤 CAS 恒为 0 → 步骤永不分发。

单测未拦截的原因：断言的是错序后的参数（`params[-1] == record_id` 恰与 bug 吻合）。
已修复两处参数顺序，并把单测改为**精确元组断言**（顺序敏感），防止回归。
教训：CAS/SQL 谓词类单测必须做真实数据库验证或全元组断言，仅断言"包含"不够。

## 9. 测试

- `tests/task/test_queued_task_cancel.py`：CAS SQL 谓词（精确元组断言参数顺序）、
  三处闸门抢占失败不调上游、终态防覆盖、守卫拦截/CANCELLED 分支槽位归还（15 用例）。
- `tests/js/test_ai_task_cancel_frontend.js`：前端链路静态断言（入口/展示/i18n/CSS）。

## 10. 运维速查

```sql
-- 排队中的任务（可取消窗口）
SELECT id, user_id, type, status, create_time FROM ai_tools
 WHERE status IN (0,3,4);
-- 已取消任务
SELECT id, user_id, status, message, completed_time FROM ai_tools WHERE status = -2;
-- 取消事件轨迹
SELECT * FROM ai_tools_log WHERE ai_tool_id = ? AND event_type IN ('user_cancelled','cancel_guard_rejected');
-- 已请求取消、尚未落终态（预处理步骤在途）
SELECT id, user_id, status, cancel_requested FROM ai_tools
 WHERE cancel_requested = 1 AND status = 4;
```

## 11. 预处理步骤在途：延迟取消

`WAITING_PARAM_PREPARE` 期间，`dispatch_step` 可能已经把步骤抢成 PROCESSING，并调用
人脸遮罩 / H3 提示词优化等上游。这时立刻把任务改成 CANCELLED 并退款，上游请求仍会
完成，平台仍要付这次预处理费用。

因此只在「状态是 4 且已有步骤 PROCESSING」（或标识已经写下）时走延迟取消：

1. 取消接口只执行 `request_cancel`（`cancel_requested=1`），不改 status、不退款。
   响应 `data.status=CANCELLING`。再次点击且状态仍是 4，仍返回 CANCELLING。
2. `dispatch_step` 在 `execute` 之前若看到 CANCELLED 或 `cancel_requested`，把本步骤
   标为 CANCELLED，不调用上游。步骤 CAS 抢到 PROCESSING 之后再读一次，命中则回滚
   该步骤并不调用上游。
3. 仍有其它步骤 PROCESSING 时，`commit_deferred_cancel` 不退款。当前步骤结束后，
   阶段检查不再 `4→0`、不再派发下一步，CAS 到 CANCELLED（要求 `cancel_requested=1`）
   并退款一次。
4. PENDING / SYNC_QUEUED，以及状态 4 但没有 PROCESSING 步骤，仍走原来的立即 CAS + 退款。
   「检查时还没有 PROCESSING，随后步骤才抢到」由提交前的再次读取挡住上游调用。

已经发出的 HTTP 无法撤回。延迟取消只保证**下一次**上游调用不会发出，退款发生在
在途步骤返回之后。

开工与推进（`0→4`、`0→3`、`0→1`、`3→1`、`4→0`）的 `transition_status` 带
`block_if_cancel_requested=True`（`AND cancel_requested=0`）。字段更新走
`update_only_fields`（及 `update_only_fields_with_cdn_sync`、
`update_only_fields_by_project_id`、`update_only_fields_by_project_id_with_cdn_sync`）。
这些函数的参数里没有 `status`，传入会抛 `TypeError`。状态迁移走
`transition_status` 或 `transition_with_cdn_sync`。CI
`scripts/lint_ai_tool_status_cas.py`（S1）会拦住旧函数名和 `status=`。

列 `ai_tools.cancel_requested` 由迁移 `no_161_20261103_add_ai_tools_cancel_requested`（revision `no_161_ai_tools_cancel_req`）添加。
前端轮询把该标识显示为「取消中」，`node.data.cancelRequested` 写入工作流快照，刷新后恢复。
