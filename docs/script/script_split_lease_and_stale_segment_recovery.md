# 剧本拆分：任务租约与僵尸段回收

## 1. 文档状态

| 项 | 说明 |
|---|---|
| 状态 | **已实现**：唯一租约令牌、owner fencing、自动续租、集中僵尸回收与恢复熔断 |
| 日期 | 2026-07-17 |
| 适用范围 | `script_split_task` 租约、`script_split_segment` 状态机、效果模式 ready 调度 |
| 相关代码 | `task/script_split_task.py`、`model/script_split_task.py`、`model/script_split_segment.py`、`services/script_split_engine.py`、`enterprise/services/script_split_quality/dependency_scheduler.py` |
| 相关文档 | [增量拆分设计](./script_parser_incremental_split_design.md)、[效果模式空间依赖](./script_split_quality_spatial_dependency_design.md) |

## 2. 背景（现象）

以 storyboard 拆分任务为例（如 task 43）：

| 现象 | 说明 |
|---|---|
| 前端一直「拆分中」 | 根任务 `status=generating`，轮询仍当进行中 |
| `logs/llm.YYYY-MM-DD.log` 长时间无新记录 | 实际**没有新的 LLM 调用** |
| app 日志周期性 | `task N 无 ready 段（K 个 waiting），让出 tick` |

典型检查点状态：

- `seg_0001`：`status=generating`（或曾超时后仍停在 generating）
- `seg_0002+`：`pending`，`spatial_dependency.mode=inherit` → **waiting** 上游

根因不是「LLM 还在跑」，而是 **段状态机与调度规则组合后的死锁/假进度**（见 §4）。

## 3. 任务租约模型（改造前问题）

### 3.1 改造前生命周期

| 时机 | 行为 | 代码位置 |
|---|---|---|
| Worker tick 领取任务 | `claim_next_task(TASK_LEASE_SECONDS)`：原子 `FOR UPDATE` 后写入 `worker_id`、`lease_until = NOW() + TASK_LEASE_SECONDS` | `model/script_split_task.py` |
| 可领取条件（改造前缺陷） | `queued` 会绕过租约条件；活跃态才检查 `lease_until`，存在两个 worker 连续领取同一 queued 任务的窗口 | 同上 |
| 单步执行中（规划 / 段生成 / 发布） | **不会自动续租** | `task/script_split_task.py` 未调用 `renew_lease` |
| 单步正常结束 | `release_lease`：`worker_id/lease_until` 置 NULL | 同上 |
| 单步异常 / 看门狗超时 | 更新根任务状态后 `release_lease` | 同上 |

改造前 `ScriptSplitTaskModel.renew_lease()` 虽已存在，但调度路径未接入，因此：

> **正常运行中不会自动延伸租期。**
> 租约仅在 claim 时设一次，在步结束时释放。

### 3.2 超时与租约常量（层级）

见 `config/constant.py` 中 `ScriptSplitConstants`，数值以运行配置为准：

| 常量 | 含义 |
|---|---|
| `LLM_TIMEOUT_SECONDS` / `LLM_HTTP_TIMEOUT_SECONDS` | 底层 HTTP / transport |
| `LLM_CALL_TIMEOUT_SECONDS` | 单段 LLM coroutine 外层 |
| `WORKER_STEP_TIMEOUT_SECONDS` | 整个调度单步看门狗 |
| `TASK_LEASE_SECONDS` | 任务租约 |
| `SCHEDULER_INTERVAL_SECONDS` | tick 间隔 |

必须满足：

```text
HTTP / transport  <  LLM_CALL  <  WORKER_STEP  <  TASK_LEASE
```

### 3.3 改造前如何避免「别人抢任务」

在**未续租**的前提下，主要依赖：

```text
WORKER_STEP_TIMEOUT_SECONDS  <  TASK_LEASE_SECONDS
```

合法持有者在看门狗时限内跑完或被 pause，期间 `lease_until` 未过期 → 其他 worker **claim 不到**同一任务。

### 3.4 改造前风险

若单步实际占用超过 `TASK_LEASE`（配置被改短、步骤变长、看门狗未覆盖的路径等），可能出现：

1. Worker A 仍在执行 LLM（线程/请求未结束）
2. 租约已过期
3. Worker B claim 成功并再次推进 → **双跑 / 状态错乱风险**

这与「未接入 `renew_lease`」直接相关。推荐方案见 §5.1。

### 3.5 必须同时修复的租约缺陷

1. `queued` 也必须满足 `lease_until IS NULL OR lease_until < NOW()`，不能成为租约过滤的例外。
2. 当前 `renew_lease(task_id)` / `release_lease(task_id)` 只按任务 ID 更新，旧 worker 可能续租或释放新 worker 的租约。
3. `worker_id` 不再只是稳定的 `hostname-pid`，而是每次 claim 生成唯一令牌：`hostname-pid-claim_uuid`（最长 64 字符）。
4. 所有 renew/release/reclaim 必须同时匹配 `task_id + worker_id`；影响行数不是 1 即视为租约丢失。

## 4. 僵尸 `generating` 段（现状问题）

### 4.1 段状态与 ready

效果模式依赖调度（`dependency_scheduler`）：

| 段 `status` | 可否进入 ready |
|---|---|
| `pending` | 可以（依赖满足时） |
| `failed` | 可以（表示等待重试，含质检失败检查点） |
| `generating` | **不可以** |
| `completed` | 不可以 |

`generating` 本意是「本步正在生成」。若 worker **崩溃、进程重启、看门狗超时后未写回 failed**，段会长期停在 `generating`：

1. 自身永不 ready
2. 下游 `inherit` 看到上游非 completed → **waiting**
3. 每 tick：`ready 空 + waiting 非空` → 让出 tick，**不调 LLM**
4. 根任务仍为 `generating` → UI 一直「拆分中」

### 4.2 与 llm 日志的关系

- UI 进度来自 **根任务状态**（`script_split_task`）
- LLM 日志仅在实际调用模型时写入
- 假进度空转时：**根任务更新/tick 日志可能有，llm.log 可以完全停更**

## 5. 已实现方案

### 5.1 步骤内自动续租

**目标**：合法运行期间持续后推 `lease_until`，避免租约先于步骤过期导致他人误 claim。

**建议位置**：`process_script_split_tasks` 在 claim 成功后、整步执行期间：

```text
claim
  → 启动续租协程（周期 owner-checked renew_lease）
  → await wait_for(_advance_one_step, WORKER_STEP)
  → finally: 取消续租协程；owner-checked release_lease
```

**已实现常量**：

| 常量 | 建议 | 约束 |
|---|---|---|
| `LEASE_RENEW_INTERVAL_SECONDS` | 120 | 必须满足 `0 < interval <= TASK_LEASE_SECONDS / 3` |
| `LEASE_RENEW_DB_TIMEOUT_SECONDS` | 15 | 单次续租数据库调用上限，必须小于续租间隔 |

接口调整为：

```python
ScriptSplitTaskModel.renew_lease(task_id, worker_id, lease_seconds) -> bool
ScriptSplitTaskModel.release_lease(task_id, worker_id) -> bool
```

数据库操作通过 `asyncio.to_thread` 执行。续租返回 False、超时或抛异常时，续租协程发出 `lease_lost`：立即取消当前编排 coroutine，不再写根任务状态。外层 finally 仍尝试 owner-checked release：本 claim 仍是 owner 时立即释放；owner 已变化时更新 0 行，不会影响新 worker。

### 5.2 僵尸 generating 回收

**目标**：claim 独占任务后，把遗留的 `generating` 收成可调度的 `failed`，使 ready 能再次选中该段。

**判定（防误杀）——不是按「空闲秒数」盲杀**：

```text
本 worker 已通过 claim 原子拿到该任务的独占租约
  AND 此时仍存在 status=generating 的段
  → 上一任持有者未正常收尾 → 视为僵尸，回收后重试
```

| 场景 | 是否 reclaim |
|---|---|
| 其他 worker 合法持有未过期租约 | **claim 失败** → 不会 reclaim |
| 本步已 claim，入口处仍有 generating | **回收**（上一 tick/进程遗留） |
| 本步 `mark_generating` 之后、LLM 进行中 | **不再 reclaim**（只在 step **入口**做一次） |
| 已 completed / failed | 不动 |

**API**：

```python
ScriptSplitSegmentModel.reclaim_stale_generating(
    task_id,
    worker_id,
    max_recoveries,
) -> StaleSegmentRecoveryResult
```

- `generating` → `failed`
- 保留 `validation_errors`、`parsed_result_json`
- **不**增加 `attempt_count`
- 写入/更新诊断项 `segment_interrupted` 和 `_stale_recovery_count`
- 方法内部在同一事务中锁定根任务并验证 `task_id + worker_id + lease_until >= NOW()`，不能只靠调用方注释
- 同一段累计达到 `STALE_SEGMENT_MAX_RECOVERIES=3` 后返回 exhausted，根任务进入可恢复的 `paused(segment_repeatedly_interrupted)`，避免无限崩溃循环
- 用户显式 resume 时把 `_stale_recovery_count` 重置为 0，开启新的人工确认恢复周期

**唯一调用点**：`process_script_split_tasks` claim 成功后、进入 `_advance_one_step` 前。普通生成、并行生成和 watchdog 分支不再各自调用，避免重复回收与模式遗漏。

### 5.3 推荐时序

```text
claim 成功（独占 + 初始 lease）
    │
    ├─ 启动 lease renew 循环
    │
    ├─ owner-checked reclaim_stale_generating
    │     └─ 达到恢复上限 → paused(segment_repeatedly_interrupted)
    │
    ├─ plan / generate / publish
    │     └─ mark_generating → LLM → completed | failed
    │
    └─ finally: 停续租 + owner-checked release_lease
```

### 5.4 与续租的关系

- **续租**：降低「A 还在跑、B 已 claim」的误启动概率。
- **reclaim**：只在「B 已合法 claim」后处理 A 留下的 generating。
- 两者配合后：正常运行靠续租独占；故障后靠过期 claim + reclaim 恢复。

### 5.5 原子领取 SQL

所有可执行状态统一受租约条件约束：

```sql
WHERE status IN ('queued', 'planning', 'generating', 'merging',
                 'validating', 'publishing', 'cancelling')
  AND (lease_until IS NULL OR lease_until < NOW())
```

`SELECT ... FOR UPDATE` 与写入唯一 `worker_id` 保持在同一事务中。

### 5.6 验收测试

- 两个 worker 竞争 queued 任务时只有一个能够领取。
- A 租约过期且 B 已领取后，A 无法续租或释放 B 的租约。
- 长步骤执行期间 `lease_until` 会周期性后移；续租数据库调用不阻塞事件循环。
- 续租返回 False、超时或异常时取消当前步骤，且不写入 paused/failed 覆盖新 owner 状态。
- claim 后一次性回收任务下全部 generating 段，保留候选与业务诊断，不增加 `attempt_count`。
- pending/failed/completed 不被回收；恢复次数达到 3 后进入可恢复 paused。
- 用户 resume 会重置 stale recovery 周期。

## 6. 运维

### 6.1 确认是否假进度

```sql
SELECT id, status, phase, progress, worker_id, lease_until, update_at
FROM script_split_task WHERE id = ?;

SELECT segment_index, segment_id, status, attempt_count,
       LEFT(validation_errors, 200) AS err, update_at
FROM script_split_segment WHERE task_id = ?
ORDER BY segment_index;
```

若根任务 `generating`、某段长期 `generating`、下游全 `pending`，且 app 反复「无 ready」，即为 §4 类问题。

### 6.2 手工捞起（代码 reclaim 落地前）

在确认**无 worker 正持有未过期租约**（或可接受中断）后：

```sql
UPDATE script_split_segment
SET status = 'failed'
WHERE task_id = ? AND status = 'generating';
```

根任务若仍为 `generating` 且租约空闲，下一 tick 会重新调度；若为 `paused`，需走 resume 接口。

### 6.3 观察项

| 信号 | 含义 |
|---|---|
| `lease_until` 在长步骤中持续后移 | 续租已生效 |
| 日志 `reclaimed N stale generating` | 僵尸回收已触发 |
| llm 日志重新有请求 | 段再次进入生成 |
| 仍无限「无 ready」 | 检查是否仍有 generating、或 blocked 依赖 |

## 7. 相关代码索引

| 模块 | 职责 |
|---|---|
| `task/script_split_task.py` | `process_script_split_tasks`：claim、单步、看门狗、release |
| `model/script_split_task.py` | `claim_next_task` / `release_lease` / `renew_lease` |
| `model/script_split_segment.py` | 段状态、`mark_generating`、`save_failure`、租约保护下的集中 reclaim |
| `services/script_split_engine.py` | `step_generate_segment`、并行批次调度 |
| `enterprise/.../dependency_scheduler.py` | ready / waiting / blocked |

## 8. 修订记录

| 日期 | 说明 |
|---|---|
| 2026-07-17 | 初版：记录现状（不续租、generating 僵尸假进度）、推荐续租与 reclaim 设计 |
| 2026-07-17 | 定稿并实现：修复 queued 租约绕过；增加 claim 唯一令牌、owner fencing、续租失败取消、集中回收及三次熔断 |
