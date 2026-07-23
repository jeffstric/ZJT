# AI Tools 任务状态与流水线步骤完整流转文档

## 1. ai_tools 状态流转图

```mermaid
stateDiagram-v2
    [*] --> PENDING : API 创建任务

    PENDING --> WAITING_PARAM_PREPARE : 有 param_prepare 步骤
    PENDING --> PROCESSING : 无步骤 / sync_mode=False
    PENDING --> SYNC_QUEUED : sync_mode=True

    WAITING_PARAM_PREPARE --> PENDING : 所有 param_prepare 步骤完成\n（apply 结果到 ai_tools）
    WAITING_PARAM_PREPARE --> FAILED : param_prepare 步骤失败\n（整个任务失败+退算力）

    PROCESSING --> COMPLETED : driver.check_status()\n→ SUCCESS
    PROCESSING --> _Failure : driver.check_status()\n→ FAILED

    SYNC_QUEUED --> COMPLETED : SyncExecutor 成功
    SYNC_QUEUED --> _Failure : SyncExecutor 失败

    _Failure --> WAITING_BEFORE_FINISH : 有替代供应商\n（创建 before_finish 步骤）
    _Failure --> FAILED : 无替代供应商\n（退算力）

    WAITING_BEFORE_FINISH --> PENDING : retry driver 执行成功\n（设新 implementation）
    WAITING_BEFORE_FINISH --> FAILED : 所有重试耗尽\n（退算力）

    COMPLETED --> [*]
    FAILED --> [*]

    note right of PENDING
        ai_tools=0, tasks=0
        主调度器(5s)拾取
    end note

    note right of PROCESSING
        ai_tools=1, tasks=1
        主调度器轮询状态
    end note

    note right of SYNC_QUEUED
        ai_tools=3, tasks=3
        SyncExecutor 子进程处理
    end note

    note right of WAITING_PARAM_PREPARE
        ai_tools=4, tasks=4
        流水线调度器(13s)分发步骤
    end note

    note right of WAITING_BEFORE_FINISH
        ai_tools=5, tasks=5
        流水线调度器(13s)分发步骤
    end note
```

## 2. 双表状态对照

系统使用 `ai_tools` 和 `tasks` 两张表跟踪任务状态，**两者必须保持同步**。主调度器仅查询 `tasks.status IN (0, 1)` 来获取待处理任务。

| ai_tools.status | tasks.status | 常量名 | 说明 |
|:-:|:-:|---|---|
| 0 | 0 | PENDING / QUEUED | 待处理 |
| 1 | 1 | PROCESSING | 处理中（已提交到外部 API） |
| 2 | 2 | COMPLETED | 处理完成 |
| -1 | -1 | FAILED | 处理失败 |
| 3 | 3 | SYNC_QUEUED | 已提交到同步任务进程池 |
| 4 | 4 | WAITING_PARAM_PREPARE | 等待参数预处理流水线完成 |
| 5 | 5 | WAITING_BEFORE_FINISH | 等待失败重试流水线完成 |

## 3. Pipeline Step 生命周期

```mermaid
flowchart TD
    subgraph 创建
        A[任务失败] --> B{有替代供应商?}
        B -->|是| C[选择优先级最高的一个未尝试供应商]
        B -->|否| D["FAILED(-1) + 退算力"]
        C --> E["顺序写入：当前 attempt=FAILED\nai_tools/tasks=WAITING_BEFORE_FINISH\n最后创建唯一 retry 步骤"]
    end

    subgraph 流水线调度器_13s
        E --> G[dispatch 唯一 retry 步骤]
        G --> I[retry driver.execute]
        I --> K["顺序写入：\n1. ai_tools.implementation = 新供应商\n2. ai_tools.status = PENDING(0)\n3. 创建新 attempt\n4. tasks.status = QUEUED(0)\n5. retry step = COMPLETED(2)"]
    end

    subgraph 主调度器_5s_重新拾取
        K --> M[_submit_new_task]
        M --> N{ai_tool.implementation 已设置?}
        N -->|是| O["create_driver_by_implementation\n使用新供应商"]
        N -->|否| P["create_driver_by_type\n用户偏好"]
        O --> Q[提交任务]
        P --> Q
    end
```

### 步骤状态

| 状态值 | 常量名 | 说明 |
|:-:|---|---|
| 0 | PENDING | 待处理 |
| 1 | PROCESSING | 处理中 |
| 2 | COMPLETED | 完成 |
| -1 | FAILED | 失败 |
| -2 | TIMEOUT | 超时 |

### 流水线阶段与步骤类型

| 阶段 | 步骤类型 | 说明 |
|---|---|---|
| param_prepare | face_mask | 人脸遮盖预处理（任务提交前） |
| before_finish | implementation_retry | 切换供应商重试（任务失败后） |

### 关键逻辑

- **不重复已尝试供应商**：候选选择按配置优先级遍历，并排除 `implementation_attempts` 中已经实际尝试过的所有供应商
- **跳过不可用的供应商**：创建步骤时检查 `is_enabled()` 和 `create_driver_by_implementation()` 能否成功
- **一次只创建一个候选**：每次供应商真实失败后，只创建优先级最高的一个备用供应商；该供应商也失败后才创建下一个
- **备用次数上限**：按 implementation attempt 去重计数，初始供应商之外最多使用 3 个不同备用供应商（`A → B → C → D`）
- **等待状态先于步骤发布**：先写当前 attempt 失败和 `ai_tools/tasks` 等待状态，最后创建唯一 retry step；Pipeline 抓到步骤时任务已经停止被主调度器处理
- **QUEUED 最后开放**：retry driver 先切换 implementation、更新 `ai_tools` 并创建新 attempt，最后更新 `tasks.status=QUEUED`；主调度器不会用旧供应商提交
- **旧数据兼容**：升级前遗留的多个 PENDING retry 步骤只执行第一个，其余标记 `legacy_multiple_candidates`

## 4. 完整任务处理流程（含同步/异步分流）

```mermaid
flowchart TD
    START(["API 创建 ai_tool\nstatus=PENDING"]) --> SCHED{"主调度器 5s\n拾取 tasks.status IN 0,1"}

    SCHED --> PP{"ai_tools.status = ?"}

    PP -->|"PENDING (0)"| SUB[_submit_new_task]

    PP -->|"PROCESSING (1)"| CHECK["_check_task_status\ndriver.check_status"]

    PP -->|"WAITING_PARAM_PREPARE (4)"| PIPE_CHECK1["_check_pipeline_stage\nPARAM_PREPARE"]

    PP -->|"WAITING_BEFORE_FINISH (5)"| PIPE_CHECK2["_check_pipeline_stage\nBEFORE_FINISH"]

    %% === 提交流程 ===
    SUB --> HAS_PREP{"有 param_prepare 步骤?"}
    HAS_PREP -->|是| WAIT_PREP["ai_tools=4, tasks=4\nWAITING_PARAM_PREPARE"]
    HAS_PREP -->|否| GET_IMPL

    GET_IMPL["获取 implementation\n优先 retry 设置 → 用户偏好"]
    GET_IMPL --> SYNC_CHECK{"sync_mode?"}

    SYNC_CHECK -->|是| SYNC_SUB["提交到 SyncExecutor\nai_tools=3, tasks=3"]
    SYNC_CHECK -->|否| CREATE_DRV["创建 driver\nsubmit_task"]

    CREATE_DRV --> SUBMIT_OK{"提交结果?"}
    SUBMIT_OK -->|成功| SET_PROC["ai_tools=1, tasks=1\nPROCESSING\n记录 project_id"]
    SUBMIT_OK -->|失败| FAIL_HANDLER

    %% === 同步任务流程 ===
    SYNC_SUB --> SYNC_EXEC["_execute_sync_task 子进程\n创建 driver\n优先 ai_tool.implementation"]
    SYNC_EXEC --> SYNC_RESULT{"SyncTaskResult"}
    SYNC_RESULT -->|成功| SYNC_SUCCESS["下载缓存\nai_tools=2, tasks=2\nCOMPLETED"]
    SYNC_RESULT -->|失败| SYNC_FAIL["_handle_task_failure\n→ visual_task._handle_task_failure\n→ enterprise retry handler"]
    SYNC_FAIL --> FAIL_HANDLER

    %% === 状态轮询 ===
    CHECK --> POLL_RESULT{"check_status 结果"}
    POLL_RESULT -->|SUCCESS| SUCCESS["下载缓存\nai_tools=2, tasks=2\nCOMPLETED"]
    POLL_RESULT -->|FAILED| FAIL_HANDLER
    POLL_RESULT -->|RUNNING| SCHED

    %% === 流水线阶段检查 ===
    PIPE_CHECK1 --> PIPE_DONE1{"步骤完成?"}
    PIPE_DONE1 -->|全部完成| APPLY["apply_results\nai_tools=0, tasks=0\n回到 PENDING"]
    PIPE_DONE1 -->|有失败| FAIL_DIRECT["ai_tools=-1, tasks=-1\nFAILED + 退算力"]
    PIPE_DONE1 -->|进行中| SCHED

    PIPE_CHECK2 --> PIPE_DONE2{"步骤状态?"}
    PIPE_DONE2 -->|retry 成功| BACK_PENDING["ai_tools 已被 retry driver\n设为 PENDING(0), tasks=0"]
    PIPE_DONE2 -->|全部失败| FAIL_FINAL["ai_tools=-1, tasks=-1\nFAILED + 退算力"]
    PIPE_DONE2 -->|进行中| SCHED

    APPLY --> SCHED

    %% === 失败处理 ===
    FAIL_HANDLER --> ENTERPRISE{"enterprise retry handler"}
    ENTERPRISE -->|有替代供应商| CREATE_STEPS["先设置 WAITING，最后创建唯一 before_finish 步骤\nai_tools=5, tasks=5"]
    ENTERPRISE -->|无替代供应商| FAIL_FINAL2["ai_tools=-1, tasks=-1\nFAILED + 退算力"]

    CREATE_STEPS --> PIPE_SCHED{"流水线调度器 13s"}
    PIPE_SCHED --> DISPATCH["分发步骤\nretry driver 执行"]
    DISPATCH --> RETRY_OK{"切换成功?"}
    RETRY_OK -->|是| BACK_PENDING2["ai_tools.implementation=新供应商\nai_tools=0, tasks=0\nPENDING"]
    RETRY_OK -->|否| RETRY_FAIL["步骤 FAILED"]
    RETRY_FAIL --> PIPE_DONE2

    BACK_PENDING2 --> SCHED

    SUCCESS --> END_NODE([结束])
    SYNC_SUCCESS --> END_NODE
    FAIL_DIRECT --> END_NODE2([结束])
    FAIL_FINAL --> END_NODE3([结束])
    FAIL_FINAL2 --> END_NODE4([结束])

    style START fill:#4CAF50,color:#fff
    style END_NODE fill:#2196F3,color:#fff
    style END_NODE2 fill:#f44336,color:#fff
    style END_NODE3 fill:#f44336,color:#fff
    style END_NODE4 fill:#f44336,color:#fff
    style FAIL_HANDLER fill:#FF9800,color:#fff
    style CREATE_STEPS fill:#9C27B0,color:#fff
    style SYNC_EXEC fill:#00BCD4,color:#fff
```

## 5. 三个调度器协作时序

```mermaid
sequenceDiagram
    participant API as API请求
    participant MAIN as 主调度器(5s)
    participant PIPE as 流水线调度器(13s)
    participant SYNC as SyncExecutor(5s)
    participant DB as 数据库

    Note over API,DB: ── 异步任务正常流程 ──
    API->>DB: 创建 ai_tool(status=0) + task(status=0)
    MAIN->>DB: 查询 tasks.status IN (0,1)
    MAIN->>DB: ai_tools.status=PENDING → _submit_new_task()
    MAIN->>DB: implementation=29, status→PROCESSING(1)

    loop 每 5s 轮询
        MAIN->>DB: check_status(project_id)
    end
    MAIN->>DB: status→COMPLETED(2)

    Note over API,DB: ── 异步任务失败+重试流程 ──
    MAIN->>DB: check_status → FAILED
    MAIN->>DB: _handle_task_failure → enterprise handler
    MAIN->>DB: 顺序写入：attempt=FAILED → ai_tools/tasks=5 → 创建唯一 pipeline_step(status=0)

    PIPE->>DB: 查询 PENDING 步骤
    PIPE->>DB: dispatch 唯一步骤 → retry driver 执行
    PIPE->>DB: 顺序写入：implementation=30，ai_tools=0，创建 attempt，最后 tasks=0，step=COMPLETED

    MAIN->>DB: 查询 tasks.status IN (0,1) → 拾取
    MAIN->>DB: 检测 ai_tool.implementation=30
    MAIN->>DB: create_driver_by_implementation(30) → 提交

    Note over API,DB: ── 同步任务流程 ──
    MAIN->>DB: 检测 sync_mode=True
    MAIN->>SYNC: executor.submit(task_id, type)
    MAIN->>DB: ai_tools=3, tasks=3 (SYNC_QUEUED)

    SYNC->>DB: 子进程: implementation→创建 driver
    SYNC->>DB: 子进程: submit_task → 结果

    SYNC->>DB: check_results() 处理结果
    SYNC->>DB: 成功→COMPLETED(2) / 失败→_handle_task_failure
```

## 6. 调度器体系

| 调度器 | 间隔 | 功能 | 入口函数 |
|---|---|---|---|
| 主任务调度器 | 5s | 查询 `tasks.status IN (0,1)` 的任务，根据 `ai_tools.status` 分发处理 | `process_task_with_retry` → `process_generate_video` |
| 流水线步骤调度器 | 13s | 分发 PENDING 步骤、检查 PROCESSING 步骤、推进 ai_tools 状态 | `PipelineProcessor.process_all_pending_steps` |
| 同步任务结果检查器 | 5s | 检查同步进程池中已完成任务的结果 | `SyncTaskExecutor.check_results` |
| 孤儿任务恢复 | 20min | 重置卡在 PROCESSING 的超时任务 | `_reset_orphan_processing_tasks` |
| RunningHub 异步轮询 | 10s | 轮询**已提交** RunningHub 异步任务状态（`external_task_id` 非空） | `process_runninghub_async_tasks` |
| 异步任务提交重试 | 7s | 槽位满时重试提交；顺带清理耗尽重试的僵尸 QUEUED | `process_pending_async_task_submissions` |
| RunningHub 槽位清理 | 30min | 清理超时槽位 | `cleanup_runninghub_slots` |

## 7. 各状态下调度器行为

| ai_tools.status | 主调度器(5s) | 流水线调度器(13s) | SyncExecutor(5s) |
|---|---|---|---|
| PENDING (0) | `_submit_new_task()` | - | - |
| PROCESSING (1) | `_check_task_status()` | - | - |
| SYNC_QUEUED (3) | 不处理 | - | `check_results()` |
| WAITING_PARAM_PREPARE (4) | `_check_pipeline_stage(PARAM_PREPARE)` | 分发/轮询步骤 | - |
| WAITING_BEFORE_FINISH (5) | `_check_pipeline_stage(BEFORE_FINISH)` | 分发/轮询步骤 | - |
| COMPLETED (2) | 不进入调度 | - | - |
| FAILED (-1) | 不进入调度 | - | - |

> **注意**：主调度器通过 `tasks.status IN (0, 1)` 查询，因此 WAITING_PARAM_PREPARE(4)、WAITING_BEFORE_FINISH(5)、SYNC_QUEUED(3) 的任务**不会**被主调度器拾取。它们由各自的专用处理器推进。

## 8. 核心代码路径索引

| 场景 | 文件 | 函数 |
|---|---|---|
| 任务提交 | `task/visual_task.py` | `_submit_new_task()` |
| 任务状态轮询 | `task/visual_task.py` | `_check_task_status()` |
| 流水线阶段检查 | `task/visual_task.py` | `_check_pipeline_stage()` |
| 统一失败处理 | `task/visual_task.py` | `_handle_task_failure()` |
| 任务成功处理 | `task/visual_task.py` | `_handle_task_success()` |
| 任务调度入口 | `task/visual_task.py` | `process_task_with_retry()` → `process_generate_video()` |
| 流水线编排 | `task/pipeline_processor.py` | `PipelineProcessor.process_all_pending_steps()` |
| 步骤创建规则 | `task/pipeline_drivers/__init__.py` | `PipelineDriverFactory.create_before_finish_steps()` |
| 供应商重试驱动 | `task/pipeline_drivers/implementation_retry_driver.py` | `ImplementationRetryPipelineDriver.execute()` |
| 企业版失败处理 | `enterprise/task/retry_handler.py` | `handle_failure_with_retry()` |
| 同步任务执行 | `task/sync_task_executor.py` | `_execute_sync_task()` / `SyncTaskExecutor.check_results()` |

## 9. 故障恢复机制

| 机制 | 间隔 | 说明 |
|---|---|---|
| 孤儿任务恢复 | 20min | 重置 `tasks.status=PROCESSING` 的超时任务为 PENDING |
| WAITING_BEFORE_FINISH 恢复 | 每次调度 | `process_task_with_retry()` 末尾检测卡在 WAITING_BEFORE_FINISH 的任务，根据 ai_tools.status 修复 tasks.status |
| 流水线步骤完成检测 | 13s | `_check_ai_tool_stage_completion()` 检测所有步骤完成后推进 ai_tools 状态 |
| 同步任务兜底 | 5s | `check_results()` 异常时强制标记 FAILED，防止永久卡住 |
| 无 project_id 的 PROCESSING 任务 | 5s | `_check_task_status()` 检测孤儿任务并重置 |

## 10. 监控 SQL

```sql
-- 1. 查看任务状态分布
SELECT a.status, COUNT(*) as cnt
FROM ai_tools a
WHERE a.created_at > DATE_SUB(NOW(), INTERVAL 24 HOUR)
GROUP BY a.status;

-- 2. 查看双表状态不一致
SELECT t.task_id, t.status as task_status, a.status as ai_tool_status
FROM tasks t
JOIN ai_tools a ON t.task_id = a.id
WHERE t.status != a.status
  AND a.created_at > DATE_SUB(NOW(), INTERVAL 24 HOUR);

-- 3. 查看 WAITING_BEFORE_FINISH 卡住的任务
SELECT a.id, a.status, a.implementation, a.message, t.status as task_status
FROM ai_tools a
JOIN tasks t ON t.task_id = a.id
WHERE a.status = 5
  AND a.created_at > DATE_SUB(NOW(), INTERVAL 24 HOUR);

-- 4. 查看流水线步骤状态分布
SELECT stage, step_type, status, COUNT(*) as cnt
FROM ai_tool_pipeline_steps
WHERE created_at > DATE_SUB(NOW(), INTERVAL 24 HOUR)
GROUP BY stage, step_type, status;

-- 5. 查看某 ai_tool 的所有流水线步骤
SELECT id, stage, step_type, step_order, status,
       JSON_EXTRACT(params, '$.target_implementation') as target,
       JSON_EXTRACT(result_data, '$.new_implementation') as new_impl,
       created_at, updated_at
FROM ai_tool_pipeline_steps
WHERE ai_tool_id = ?
ORDER BY id;

-- 6. 查看实现方重试成功率
SELECT
    JSON_EXTRACT(params, '$.failed_implementation') as failed_impl,
    JSON_EXTRACT(params, '$.target_implementation') as target_impl,
    status,
    COUNT(*) as cnt
FROM ai_tool_pipeline_steps
WHERE stage = 'before_finish'
  AND step_type = 'implementation_retry'
  AND created_at > DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY failed_impl, target_impl, status
ORDER BY cnt DESC;
```

## 11. 失败原因写入约束

外部视频驱动返回失败时，`result["error"]` 可能是字符串，也可能是类似 `{"code": "...", "message": "..."}` 的对象。统一失败入口 `_handle_task_failure()` 会先通过 `_normalize_failure_reason()` 将失败原因转换为字符串，再写入 `implementation_attempts.error_message` 和 `ai_tools.message`。

新增或修改驱动时建议优先返回字符串错误；如果必须返回对象，需要确保对象中包含可读的 `message` 字段，便于落库和前端展示。不要将 dict/list 等 Python 对象直接作为 PyMySQL 参数写入文本字段，否则会触发 `dict can not be used as parameter`。
