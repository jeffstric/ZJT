# RunningHub 并发控制机制

## 概述

RunningHub API 对并发请求数量有限制（最多3个并发），当超过限制时会返回 `TASK_QUEUE_MAXED` 错误。为了避免这个问题，我们实现了一套完整的并发控制机制。

该机制同时支持两套任务系统：
- **旧任务系统**：`tasks` + `ai_tools` 表（视频生成等）
- **异步任务系统**：`async_tasks` 表（音频生成、人脸遮盖视频、图片人脸遮盖等）

## 核心设计

### 1. 槽位管理表

创建了 `runninghub_slots` 表来跟踪当前占用的并发槽位：

```sql
CREATE TABLE `runninghub_slots` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `task_id` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'source=task 时存 tasks.id，source=async 时存 async_tasks.id',
    `project_id` VARCHAR(100) DEFAULT NULL COMMENT 'RunningHub项目ID',
    `task_type` TINYINT NOT NULL COMMENT '任务类型(10-LTX2.0, 11-Wan2.2, 1-异步音频, 2-异步视频人脸遮盖, 3-异步图片人脸遮盖)',
    `source` VARCHAR(10) NOT NULL DEFAULT 'task' COMMENT '来源: task-旧任务系统, async-异步任务系统',
    `status` TINYINT NOT NULL DEFAULT 1 COMMENT '状态: 1-槽位占用中, 2-已释放',
    `acquired_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `released_at` DATETIME NULL DEFAULT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_task_id_source` (`task_id`, `source`),
    KEY `idx_project_id` (`project_id`)
);
```

**核心设计**：通过 `task_id` + `source` 唯一键标识每个槽位。
- `source='task'` 时，`task_id` 存储 `tasks.id`（tasks 表主键）
- `source='async'` 时，`task_id` 存储 `async_tasks.id`（async_tasks 表主键）

### 2. 槽位生命周期

#### 旧任务系统（tasks + ai_tools 表）

槽位与 `tasks` 表的生命周期绑定：

1. **槽位获取**：Task 创建时（status=0），尝试获取槽位
2. **槽位占用**：Task 提交成功后，更新 `project_id`
3. **槽位释放**：Task 完成（status=2）或失败（status=-1）时，释放槽位

#### 异步任务系统（async_tasks 表）

槽位与 `async_tasks` 表的生命周期绑定：

1. **槽位获取**：创建 `async_tasks` 记录后，调用 `submit_with_slot_management()` 获取槽位
2. **槽位占用**：提交到 RunningHub 成功后，更新槽位的 `project_id`
3. **槽位释放**：轮询器检测到任务完成/失败/超时时，释放槽位

**注意**：两套系统共享同一组槽位配额（`max_concurrent_slots`），确保 RunningHub 总并发不超限。

### 3. 异步任务后台重试机制

当 `async_tasks` 记录创建时槽位已满，系统会自动安排重试：

1. **立即安排重试**：槽位满时，不标记任务失败，而是调用 `AsyncTasksModel.schedule_retry()` 设置 `next_retry_at`
2. **后台任务处理**：`process_pending_async_task_submissions()` 每7秒扫描可重试任务
3. **指数退避**：重试延迟遵循 30s → 60s → 120s → 300s → 300s 的指数退避策略
4. **最大重试次数**：默认最多重试5次，超过后标记任务为 FAILED

#### async_tasks 表新增字段

```sql
ALTER TABLE async_tasks ADD COLUMN retry_count INT NOT NULL DEFAULT 0 COMMENT '重试次数';
ALTER TABLE async_tasks ADD COLUMN next_retry_at DATETIME DEFAULT NULL COMMENT '下次重试时间';
ALTER TABLE async_tasks ADD COLUMN max_retries INT NOT NULL DEFAULT 5 COMMENT '最大重试次数';
```

#### 重试任务查询

```python
# 获取可重试的任务（next_retry_at <= NOW 且 retry_count < max_retries）
retry_tasks = AsyncTasksModel.get_ready_to_retry_tasks(limit=50)
```

#### 后台任务处理流程

```
1. 定时任务每7秒执行 process_pending_async_task_submissions()
   ↓
2. 查询可重试任务: status=QUEUED, next_retry_at <= NOW, retry_count < max_retries
   ↓
3. 对每个任务:
   - 获取槽位
   - 调用 driver.submit_task() 提交
   - 成功: 原子更新 external_task_id、将 status 改为 PROCESSING，并清空 next_retry_at
   - 失败: 释放槽位，安排下次重试
   ↓
4. 轮询任务 (process_runninghub_async_tasks) 继续监控已提交任务的状态
```

提交成功后的三个字段必须在同一次数据库更新中完成。若只更新
`external_task_id`，任务仍满足 `status=QUEUED AND next_retry_at <= NOW()`，会被下一个
7 秒调度周期再次提交，并覆盖上一次的外部任务 ID。

### 4. 队列处理机制

#### 问题
- **队列挤压**：槽位满时，如果不处理任务，会导致每次调度都查询相同的任务
- **队列跳过**：如果直接跳过任务，后面的任务可能永远得不到处理

#### 解决方案：动态延迟机制

```python
from model.runninghub_slots import RunningHubSlot

# 如果是 RunningHub 任务且状态为0（未提交）
if is_runninghub and task.status == 0:
    # 尝试获取槽位
    slot_acquired = RunningHubSlotsModel.try_acquire_slot(
        task_id=task.id,
        task_type=ai_tool.type,
        source=RunningHubSlot.SOURCE_TASK
    )

    if not slot_acquired:
        # 槽位已满，延迟此任务
        delay_seconds = 30  # 延迟30秒
        next_trigger = datetime.now() + timedelta(seconds=delay_seconds)
        TasksModel.update_by_task_id(
            task.task_id,
            next_trigger=next_trigger
        )
        continue  # 跳过此任务，处理下一个
```

**工作原理**：
1. 槽位满时，将任务的 `next_trigger` 延迟30秒
2. 延迟后的任务暂时退出查询范围（`next_trigger <= NOW()`）
3. 30秒后任务重新进入查询范围，再次尝试获取槽位
4. 这样既避免了队列挤压，又保证了任务最终会被处理

## 工作流程

### 旧任务系统提交流程（视频生成）

```
1. 前端提交4个视频生成请求
   ↓
2. 创建4个 ai_tools 记录和 tasks 记录（status=0）
   ↓
3. 调度器每11秒执行一次
   ↓
4. 查询待处理任务（next_trigger <= NOW()）
   ↓
5. 遍历每个任务：
   - Task 1: 尝试获取槽位 → 成功（1/3）→ 提交到 RunningHub
   - Task 2: 尝试获取槽位 → 成功（2/3）→ 提交到 RunningHub
   - Task 3: 尝试获取槽位 → 成功（3/3）→ 提交到 RunningHub
   - Task 4: 尝试获取槽位 → 失败（3/3）→ 延迟30秒
   ↓
6. 30秒后，Task 4 重新进入队列
   ↓
7. 如果 Task 1/2/3 中有任务完成，槽位释放
   ↓
8. Task 4 获取槽位成功 → 提交到 RunningHub
```

### 异步任务系统提交流程（音频、人脸遮盖视频、图片人脸遮盖）

```
1. 前端/MCP 提交音频生成请求
   ↓
2. 调用 driver.submit_with_slot_management()
   ↓
3. 创建 async_tasks 记录（status=QUEUED）
   ↓
4. 尝试获取槽位
   - 成功 → 提交到 RunningHub → 更新 external_task_id
   - 失败 → 槽位满，安排重试 (schedule_retry) → 返回 503
   ↓
5. 后台任务 process_pending_async_task_submissions() 每7秒扫描
   ↓
6. 对每个可重试任务（next_retry_at <= NOW）:
   - 获取槽位
   - 提交到 RunningHub
   - 原子更新 external_task_id、status=PROCESSING、next_retry_at=NULL
   ↓
7. 轮询器 process_runninghub_async_tasks() 每10秒检查任务状态
   ↓
8. 任务终态时（SUCCESS/FAILED/TIMEOUT），释放槽位
```

### 异步任务重试流程

```
槽位满时：
1. submit_with_slot_management() 返回 {error_type: 'SLOT_FULL', retry: True}
2. 调用 AsyncTasksModel.schedule_retry() 设置 next_retry_at
3. 后台任务在 next_retry_at <= NOW 时重新尝试获取槽位
4. 成功后原子更新 external_task_id、status=PROCESSING、next_retry_at=NULL

指数退避：
- retry_count=0: 30秒
- retry_count=1: 60秒
- retry_count=2: 120秒
- retry_count=3: 300秒
- retry_count=4+: 300秒（最多5分钟）
```

### 错误处理

#### 上游并发超限错误（api queue limit reached / TASK_QUEUE_MAXED）

**根因**：当多个系统共用同一个 RunningHub API Key 时，本地 `runninghub_slots` 槽位表只统计**本系统**占用的并发，无法感知其他系统在跑的任务，于是本地"还有空槽"、上游账号实际并发已满 → RunningHub 服务端返回 `api queue limit reached, please retry later` / `TASK_QUEUE_MAXED` 等错误。这类错误本质是**临时性拥堵**。

即使有本地槽位控制，这类上游拥堵错误仍可能发生。处理方式：**识别为可重试错误，自动延迟重试，而非直接判失败、退算力**。

##### 1. 错误识别（utils/runninghub_error.py）

通过 RunningHub 响应的 `errorCode` 精确识别：当 `errorCode == '421'`（错误码常量见 `config/constant.py: RUNNINGHUB_QUEUE_LIMIT_ERROR_CODE`）时判定为上游拥堵。识别仅依据 `errorCode`，与 `errorMessage` 文本无关：

```python
from utils.runninghub_error import is_upstream_congested_error

if error_code or error_message:
    if is_upstream_congested_error(error_code):
        # 命中 → 返回自动重试标记（不判失败）
        return self._build_upstream_congested_result()
        # => {"success": False, "retry": True, "retry_reason": "UPSTREAM_CONGESTED", ...}
```

所有 RunningHub 视频驱动（ltx2.3 / ltx2 / wan22 / digital_human / digital_human_ltx2_3_voice / qwen_multi_angle）和异步驱动均接入该识别。

##### 2. 视频任务（tasks 表）—— 不消耗重试次数的延迟重试

`task/visual_task.py: _submit_new_task_with_driver` 检测到 `retry_reason=UPSTREAM_CONGESTED` 时：释放本地槽位 → 状态回 `QUEUED` → 设置 `next_trigger` 延迟 → 返回 True（外层 `process_task_with_retry` 因此**不增加 try_count**、不退算力、不切换实现方）。延迟到期后任务重新进入调度，重新获取槽位并提交，上游恢复即成功。靠 `_check_task_expiration`（`task_expire_days`）兜底防止无限重试。

```python
if result.get("retry") and result.get("retry_reason") == "UPSTREAM_CONGESTED" \
        and ai_tool_type in RUNNINGHUB_TASK_TYPES:
    RunningHubSlotsModel.release_slot(rh_task.id, source=RunningHubSlot.SOURCE_TASK)
    delay = get_dynamic_config_value("runninghub", "upstream_congest_retry_delay",
                                     default=RUNNINGHUB_UPSTREAM_CONGEST_RETRY_DELAY_DEFAULT)
    TasksModel.update_by_task_id(task_id, status=TASK_STATUS_QUEUED,
                                 next_trigger=datetime.now() + timedelta(seconds=delay))
    return True  # 返回 True → 外层不增加 try_count
```

##### 3. 异步任务（async_tasks 表）—— 指数退避重试

`task/async_drivers/base_async_driver.py` 检测到上游拥堵时：释放槽位 → `AsyncTasksModel.schedule_retry()` 安排重试（复用与本地槽位满相同的指数退避：30s→60s→120s→300s→300s，受 `max_retries` 限制），不标记 FAILED。

**效果**：用户看到的不再是"生成失败"，而是任务自动排队重试，上游通常几十秒内恢复即可成功提交。

## API 说明

### RunningHubSlotsModel

#### count_active_slots()
统计当前活跃的槽位数量

```python
count = RunningHubSlotsModel.count_active_slots()
# 返回: 0-3
```

#### try_acquire_slot(task_id, task_type, source, max_slots=None)
统一获取槽位（带并发检查，幂等操作），通过 `source` 参数区分任务来源。

**幂等机制**：使用 `INSERT ... ON DUPLICATE KEY UPDATE` 实现，解决任务重试时旧记录（status=2）仍存在导致唯一键冲突的问题。同一任务多次调用结果一致：
- 已持有活跃槽位（status=1）→ 直接返回 True
- 存在已释放记录（status=2）→ 重新激活为 status=1
- 不存在记录 → 插入新记录

```python
from model.runninghub_slots import RunningHubSlot

# 旧任务系统
success = RunningHubSlotsModel.try_acquire_slot(
    task_id=task.id,           # tasks.id
    task_type=10,              # 10-LTX2.0, 11-Wan2.2
    source=RunningHubSlot.SOURCE_TASK
)

# 异步任务系统
success = RunningHubSlotsModel.try_acquire_slot(
    task_id=async_task.id,     # async_tasks.id
    task_type=1,               # 1-异步音频, 2-异步视频人脸遮盖, 3-异步图片人脸遮盖
    source=RunningHubSlot.SOURCE_ASYNC
)
# 返回: True-成功, False-槽位已满
```

#### update_project_id(task_id, project_id, source)
更新槽位的 project_id（任务提交成功后）

```python
RunningHubSlotsModel.update_project_id(task.id, project_id, source=RunningHubSlot.SOURCE_TASK)
```

#### release_slot(task_id, source)
通过 task_id + source 释放槽位（统一方法，替代旧的按来源分别释放）

```python
RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_TASK)
RunningHubSlotsModel.release_slot(async_task.id, source=RunningHubSlot.SOURCE_ASYNC)
```

#### release_slot_by_project_id(project_id)
通过 project_id 释放槽位

```python
RunningHubSlotsModel.release_slot_by_project_id(project_id)
```

#### get_slot(task_id, source)
通过 task_id + source 获取槽位信息

```python
slot = RunningHubSlotsModel.get_slot(task.id, source=RunningHubSlot.SOURCE_TASK)
```

#### cleanup_stale_slots(timeout_minutes=60)
清理超时的槽位（超过指定时间仍未完成的任务）

```python
cleaned = RunningHubSlotsModel.cleanup_stale_slots(timeout_minutes=60)
# 返回: 清理的槽位数量
```

## 监控和维护

### 查看当前槽位使用情况

```sql
-- 查看活跃槽位
SELECT * FROM runninghub_slots WHERE status = 1;

-- 按来源统计槽位使用情况
SELECT
    source,
    task_type,
    COUNT(*) as active_count
FROM runninghub_slots
WHERE status = 1
GROUP BY source, task_type;
```

### 查看待重试的异步任务

```sql
-- 查看所有待重试的异步任务
SELECT
    id,
    implementation,
    status,
    retry_count,
    max_retries,
    next_retry_at,
    error_message
FROM async_tasks
WHERE status = 0
  AND next_retry_at IS NOT NULL
  AND next_retry_at <= NOW()
  AND retry_count < max_retries
ORDER BY next_retry_at;

-- 按状态统计异步任务
SELECT
    status,
    COUNT(*) as cnt
FROM async_tasks
GROUP BY status;

-- 查看超过最大重试次数的任务
SELECT
    id,
    implementation,
    retry_count,
    max_retries,
    error_message
FROM async_tasks
WHERE retry_count >= max_retries AND status = 0;
```

### 清理异常槽位

如果发现槽位长时间未释放，可以手动清理：

```sql
-- 清理超过1小时未完成的槽位
UPDATE runninghub_slots
SET status = 2, released_at = NOW()
WHERE status = 1
AND acquired_at < DATE_SUB(NOW(), INTERVAL 60 MINUTE);
```

或使用代码：

```python
from model import RunningHubSlotsModel

# 清理超过60分钟的槽位
cleaned_count = RunningHubSlotsModel.cleanup_stale_slots(timeout_minutes=60)
print(f"Cleaned {cleaned_count} stale slots")
```

## 配置参数

### 可调整参数

1. **最大槽位数**：默认3个
   - 配置文件：`config.yml` 中的 `runninghub.max_concurrent_slots`
   - 示例配置：
     ```yaml
     runninghub:
       host: "https://www.runninghub.cn"
       api_key: "xxx"
       max_concurrent_slots: 3  # RunningHub 最大并发槽位数量
       slot_timeout_minutes: 120  # 槽位超时时间（分钟），默认2小时
     ```
   - 建议：根据 RunningHub 实际并发限制调整（通常为3）
   - 注意：修改配置后需要重启服务生效

2. **槽位超时时间**：默认120分钟（2小时）
   - 配置文件：`config.yml` 中的 `runninghub.slot_timeout_minutes`
   - 超时后，系统自动将槽位状态设置为已完成，释放占用

3. **延迟时间**：默认30秒
   - 位置：`process_task_with_retry` 函数中的 `delay_seconds = 30`
   - 建议：根据任务处理速度调整，太短会频繁查询，太长会影响响应速度

4. **上游拥堵自动重试延迟**：默认30秒
   - 动态配置项：`runninghub.upstream_congest_retry_delay`（秒，可热更新）
   - 作用：检测到上游并发超限（api queue limit reached / TASK_QUEUE_MAXED 等）时，视频任务的延迟重试间隔；异步任务沿用既有指数退避（30s→60s→120s→300s→300s）
   - 识别依据：RunningHub 响应 `errorCode == '421'`（常量 `config/constant.py: RUNNINGHUB_QUEUE_LIMIT_ERROR_CODE`），命中即触发自动重试而非直接判失败

5. **调度间隔**：默认11秒
   - 位置：`task/scheduler.py` 中的 `IntervalTrigger(seconds=11)`
   - 建议：不要设置太短，避免频繁查询数据库

## 优势

1. **避免 TASK_QUEUE_MAXED 错误**：通过槽位控制，确保不超过并发限制
2. **公平调度**：按 `created_at` 排序，先创建的任务优先处理
3. **避免队列挤压**：延迟机制让槽位满时的任务暂时退出查询范围
4. **避免队列跳过**：延迟后的任务会重新进入队列，确保最终被处理
5. **统一 API**：同步和异步任务共用同一套槽位管理接口，通过 `source` 参数区分
6. **易于监控**：可以通过数据库查询实时了解槽位使用情况

## 注意事项

1. **数据库迁移**：首次部署需要执行数据库迁移脚本

2. **槽位清理**：系统已内置定时清理任务
   - 定时任务 `cleanup_runninghub_slots` 每30分钟执行一次
   - 默认清理超过2小时（120分钟）仍处于处理中的槽位
   - 超时时间可通过配置文件调整：`runninghub.slot_timeout_minutes`
   - 代码位置：`task/runninghub_slots_cleanup.py`

3. **监控告警**：建议监控槽位使用率，如果长期满载可能需要优化或增加资源

4. **日志查看**：关键日志包含 `RunningHub slot` 关键词，便于排查问题

---

## 多密钥轮换 + 熔断探测（密钥池）

> **商业版专属功能**。社区版后台保留入口和功能介绍，但不加载多密钥配置，
> 所有任务始终使用全局 `runninghub.api_key`。

开源仓库中的 `task/runninghub_key_pool.py` 是公共门面和社区空实现。只有经过
企业模块加载器成功注册的商业 Provider 才能开启管理 API 和运行时能力；修改
`edition.mode`、创建空 `enterprise/` 目录或写入多密钥数据库配置均不会启用该功能。

管理入口位于 admin 后台「RH密钥池」。社区版访问管理 API 返回 403。商业版的
配置格式、选择策略、故障隔离和运维说明位于私有企业包文档中。

