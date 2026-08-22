# 下载队列解耦方案（download_queue）

## 背景

`visual_task` 主循环（scheduler 每 5s 跑 `generate_video` job，`max_instances=1`，串行处理所有 PROCESSING 任务）原在 `_handle_task_success` 里同步 `await download_and_cache(...)` 下载上游生成结果。单个下载耗时可达分钟级，导致：

- 主循环串行处理，一个慢下载卡住后续所有任务的提交 / 轮询 / 完成回调
- APScheduler 刷屏 `Execution ... skipped: maximum number of running instances reached (1)`
- 用户点击生成后长时间无进度反馈

核心矛盾：主循环既驱动「状态机推进」（毫秒级），又做「IO 下载」（分钟级）。本方案将二者解耦。

## 方案：DB 队列 + 独立 scheduler job

与现有架构（`BackgroundScheduler` + `_run_async_task` 临时 `asyncio.run`）同构：派发即一次 `INSERT`，消费由独立 job 轮询表。**DB 是唯一真相源**，服务重启后 pending 行与租约过期的 processing 行自动恢复。

### 数据流

```
visual_task 主循环（每 5s）
  └─ _check_task_status → 上游返回 SUCCESS
     └─ _handle_task_success（task/visual_task.py）
        ├─ is_local_path（/upload/ 开头）→ 直接走原 COMPLETED 逻辑（不进队列）
        └─ 远程 URL → 派发：
           1. ai_tools.status → DOWNLOADING(6)
           2. tasks.status   → COMPLETED（退出主队列，不再被轮询）
           3. INSERT download_queue（UNIQUE ai_tool_id 幂等）
           4. return True（主循环立即处理下一个任务）
           ※ 仅当 INSERT 抛 DB 异常时，fallback 同步下载（任务不丢）

download_queue_worker（每 DOWNLOAD_POLL_INTERVAL=5s，独立 job，max_instances=1）
  └─ while 持续 claim（事务内领新行 + 回收租约孤儿），受 MAX_BATCHES_PER_TICK 上限
     └─ asyncio.gather 并发 DOWNLOAD_DISPATCHER_CONCURRENCY=6 个下载
        ├─ 成功 → ai_tools COMPLETED + 本地/CDN URL + mark attempt + TASK_COMPLETED 日志
        ├─ 失败未达上限 → reschedule + 指数退避（20/60/180s）
        └─ 失败达 max_try → 用 remote_url 兜底 + COMPLETED（H3）
```

### 新增表 `download_queue`

定义见 `model/download_queue.py` 末尾 `CREATE_TABLE_SQL`，迁移脚本 `alembic/versions/20260702_download_queue.py`。

| 字段 | 说明 |
|---|---|
| `ai_tool_id` UNIQUE | 幂等去重，一个任务只入队一次 |
| `status` | 0=待处理 1=处理中 2=成功 -1=失败(已兜底 COMPLETED) |
| `worker_id` + `lease_until` | 抢占租约；崩溃遗留行靠租约过期回收 |
| `next_trigger` | 退避后的下次可 claim 时间 |
| `try_count` / `max_try` | 重试计数 |

### 状态机（ai_tools.status 新增 DOWNLOADING=6）

`DOWNLOADING=6` 表示「远程生成已完成，结果正在下载」。该状态**不被**主队列 `list_by_type_and_status([0,1])` 命中，故不再轮询上游 API。前端把它归类为「处理中」即可。

## 关键设计决策

| 编号 | 决策 | 落地 |
|---|---|---|
| **M1** | enqueue 三态：DB 异常才 fallback 同步下载；旧行 `status=1`（正在处理）返回 `ALREADY_PROCESSING` 不覆盖、不 fallback | `DownloadQueueModel.enqueue` + `ON DUPLICATE KEY UPDATE IF(status=1,...)` |
| **M2** | 单次 tick 批数上限，防 while 无界阻塞退化成新阻塞源 | `DOWNLOAD_MAX_BATCHES_PER_TICK` |
| **M3** | 租约 > 单次下载超时（硬约束），否则正在跑的下载被误回收 | `DOWNLOAD_LEASE_SECONDS(1200) > DOWNLOAD_PER_ATTEMPT_TIMEOUT(300)`，注释锁死 |
| **P1** | 租约回收：claim 同时领新行 + 回收 `status=1 AND lease_until<NOW()` 孤儿 | `claim_pending` 事务内 `SELECT ... FOR UPDATE` |
| **P2** | before_finish 重试复用同一 ai_tool_id，覆盖非处理中的旧行 | `ON DUPLICATE KEY UPDATE IF(status=1, 原值, 新值)` |
| **H3** | 下载失败达 max_try 用 remote_url + COMPLETED（保留「下载失败≠任务失败」语义） | `_process_one` 兜底分支 |
| **P3** | 写盘不阻塞事件循环（CLAUDE.md 第1条） | `media_cache` 写盘走模块级长寿 executor + `wait_for`（`utils/download_io_pool.py`） |
| **P4** | job 内 while 持续满载 | `process_download_queue` |
| **P6** | connector 泄漏修复（原成功 return 跳过 close） | 每 attempt 独立 connector，session 退出自动关闭 |
| **P8** | 下载环节日志挪到 worker + 记录 queue_wait_ms | `_process_one` 的 DOWNLOAD_COMPLETED/RETRY_SCHEDULED/MAX_RETRY_EXCEEDED |

## 扩散面（status=6 的已知影响）

- 主队列 / audio / stuck_tasks：查 **tasks 表**，派发时已置 COMPLETED，不受影响
- 前端任务列表（`AIToolsModel.list_by_user`）：WHERE 不含 status，DOWNLOADING 任务照常返回，前端按 status 归类显示为「处理中」即可
- 统计（`get_implementation_stats`，`status IN (2,-1)`）：DOWNLOADING 暂不计入成功/失败，下载完成前轻微拉低成功率（影响小）
- `list_processing_by_user(status=1)`：无调用方，无影响

`_process_one` 禁止函数内 `import asyncio`。Python 会把 `asyncio` 变成整个函数的局部变量，
函数开头的 `await asyncio.wait_for(...)` 会立刻 `UnboundLocalError`；若 `gather(return_exceptions=True)`
再把它吞掉，队列行会永远停在 `status=1`，界面一直「处理中」。`process_download_queue` 必须把
gather 的异常结果打到日志。

## 运维 / 排查

```sql
-- 队列积压概览
SELECT status, COUNT(*) FROM download_queue GROUP BY status;
-- 处理中超租约的孤儿（应被下个 tick 回收）
SELECT id, ai_tool_id, worker_id, lease_until FROM download_queue
 WHERE status=1 AND lease_until < NOW();
-- 失败兜底记录
SELECT id, ai_tool_id, error_message, update_at FROM download_queue
 WHERE status=-1 ORDER BY update_at DESC LIMIT 20;
```

**回滚**：将 `_handle_task_success` 的 else 分支恢复为同步 `await download_and_cache(...)` 即可。`download_queue` 表保留无害，worker job 可单独停（删 `download_queue_worker` job）。

## 上线步骤

1. 执行迁移：`alembic upgrade head`（建 `download_queue` 表）
2. 重启服务：scheduler 自动注册 `download_queue_worker` job
3. 观察日志：`download_queue worker=... batch=... claimed N rows` / `tick done`

## 事故记录（2026-08-23）：worker 静默瘫痪 UnboundLocalError

**症状**：08-21 14:49 部署后，download_queue 全部任务卡死（453 行 status=1、0 成功 0 失败），
worker 每 5s 正常 claim，但下载从未发生、无任何 OK/FAIL 日志，租约过期后无限循环重新认领。

**根因**：d9390c4c（供应商切换差价结算）在 `_process_one` 成功分支/GIVEUP 分支内加了 `import asyncio`。
Python 作用域规则：**函数内任何位置出现 `import asyncio`，整个函数的 `asyncio` 都变为局部变量**。
下载代码（`asyncio.wait_for`）在 import 执行前引用 → `UnboundLocalError`；且
`except asyncio.TimeoutError:` 子句求值时再次抛错，**原始异常被遮蔽**后逃逸，
被 `asyncio.gather(..., return_exceptions=True)` 静默吞掉 → 无日志、行永久停留 status=1。

**修复**：删除 `_process_one` 内两处 `import asyncio`（模块顶部已有）；`visual_task.py` 同模式 3 处
（520/954/1448 行，当时因引用在 import 之后而无害）一并清理：顶部补 `import asyncio` + 删函数内 import。

**教训**：禁止在函数内 `import asyncio`（及任何函数内将多次引用的标准库模块 import 放函数内）；
函数内 import 会污染整个函数作用域，且 except 子句求值异常会遮蔽原始异常，此类故障无任何日志、
极难定位。统一把 import 放模块顶部。可用以下脚本扫描同类隐患（函数内 import asyncio 且 import 前有引用）：

```python
import ast, os
for dirpath, _, files in os.walk('task'):
    for f in files:
        if not f.endswith('.py'): continue
        tree = ast.parse(open(os.path.join(dirpath, f)).read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                imports = [n.lineno for n in ast.walk(node)
                           if isinstance(n, ast.Import) and any(a.name == 'asyncio' for a in n.names)]
                usages = [n.lineno for n in ast.walk(node)
                          if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'asyncio']
                if imports and any(u < min(imports) for u in usages):
                    print(f'{dirpath}/{f}:{node.lineno} {node.name}')
```

