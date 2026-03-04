# RunningHub 并发控制机制

## 概述

RunningHub API 对并发请求数量有限制（最多3个并发），当超过限制时会返回 `TASK_QUEUE_MAXED` 错误。为了避免这个问题，我们实现了一套完整的并发控制机制。

## 核心设计

### 1. 槽位管理表

创建了 `runninghub_slots` 表来跟踪当前占用的并发槽位：

```sql
CREATE TABLE `runninghub_slots` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `task_id` INT UNSIGNED NOT NULL COMMENT 'tasks表的task_id (ai_tools.id)',
    `task_table_id` INT UNSIGNED NOT NULL COMMENT 'tasks表的主键id',
    `project_id` VARCHAR(100) DEFAULT NULL COMMENT 'RunningHub项目ID',
    `task_type` TINYINT NOT NULL COMMENT '任务类型(10-LTX2.0, 11-Wan2.2)',
    `status` TINYINT NOT NULL DEFAULT 1 COMMENT '状态: 1-槽位占用中, 2-已释放',
    `acquired_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `released_at` DATETIME NULL DEFAULT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_task_table_id` (`task_table_id`)
);
```

### 2. 槽位生命周期

槽位与 `tasks` 表的生命周期绑定：

1. **槽位获取**：Task 创建时（status=0），尝试获取槽位
2. **槽位占用**：Task 提交成功后，更新 `project_id`
3. **槽位释放**：Task 完成（status=2）或失败（status=-1）时，释放槽位

### 3. 队列处理机制

#### 问题
- **队列挤压**：槽位满时，如果不处理任务，会导致每次调度都查询相同的任务
- **队列跳过**：如果直接跳过任务，后面的任务可能永远得不到处理

#### 解决方案：动态延迟机制

```python
# 如果是 RunningHub 任务且状态为0（未提交）
if is_runninghub and task.status == 0:
    # 尝试获取槽位
    slot_acquired = RunningHubSlotsModel.try_acquire_slot(
        task_table_id=task.id,
        task_id=task.task_id,
        task_type=ai_tool.type
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

### 任务提交流程

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

### 错误处理

#### TASK_QUEUE_MAXED 错误

即使有槽位控制，RunningHub 服务端仍可能返回 `TASK_QUEUE_MAXED` 错误（例如服务端队列已满）。处理方式：

```python
if error_msg == "TASK_QUEUE_MAXED":
    logger.warning(f"RunningHub queue maxed for task {task_id}, will retry later")
    # 延迟60秒后重试，不增加重试计数
    next_trigger = datetime.now() + timedelta(seconds=60)
    TasksModel.update_by_task_id(task_id, next_trigger=next_trigger)
    return True  # 返回True避免增加重试计数
```

## API 说明

### RunningHubSlotsModel

#### count_active_slots()
统计当前活跃的槽位数量

```python
count = RunningHubSlotsModel.count_active_slots()
# 返回: 0-3
```

#### try_acquire_slot(task_table_id, task_id, task_type, max_slots=3)
尝试获取槽位（带并发检查）

```python
success = RunningHubSlotsModel.try_acquire_slot(
    task_table_id=task.id,
    task_id=task.task_id,
    task_type=10  # 10-LTX2.0, 11-Wan2.2
)
# 返回: True-成功, False-槽位已满
```

#### update_project_id(task_table_id, project_id)
更新槽位的 project_id（任务提交成功后）

```python
RunningHubSlotsModel.update_project_id(task.id, project_id)
```

#### release_slot_by_project_id(project_id)
通过 project_id 释放槽位

```python
RunningHubSlotsModel.release_slot_by_project_id(project_id)
```

#### release_slot_by_task_table_id(task_table_id)
通过 task_table_id 释放槽位

```python
RunningHubSlotsModel.release_slot_by_task_table_id(task.id)
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

-- 统计槽位使用情况
SELECT 
    task_type,
    COUNT(*) as active_count
FROM runninghub_slots 
WHERE status = 1
GROUP BY task_type;
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
     ```
   - 建议：根据 RunningHub 实际并发限制调整（通常为3）
   - 注意：修改配置后需要重启服务生效

2. **延迟时间**：默认30秒
   - 位置：`process_task_with_retry` 函数中的 `delay_seconds = 30`
   - 建议：根据任务处理速度调整，太短会频繁查询，太长会影响响应速度

3. **TASK_QUEUE_MAXED 重试延迟**：默认60秒
   - 位置：`_submit_new_task` 函数中的 `timedelta(seconds=60)`
   - 建议：根据 RunningHub 服务端队列恢复速度调整

4. **调度间隔**：默认11秒
   - 位置：`task/scheduler.py` 中的 `IntervalTrigger(seconds=11)`
   - 建议：不要设置太短，避免频繁查询数据库

## 优势

1. **避免 TASK_QUEUE_MAXED 错误**：通过槽位控制，确保不超过并发限制
2. **公平调度**：按 `created_at` 排序，先创建的任务优先处理
3. **避免队列挤压**：延迟机制让槽位满时的任务暂时退出查询范围
4. **避免队列跳过**：延迟后的任务会重新进入队列，确保最终被处理
5. **容错性强**：支持通过 `project_id` 或 `task_table_id` 释放槽位
6. **易于监控**：可以通过数据库查询实时了解槽位使用情况

## 注意事项

1. **数据库迁移**：首次部署需要执行数据库迁移脚本
   ```bash
   mysql -u username -p database_name < model/sql/migrations/2026-01-09-15-17_create_runninghub_slots.sql
   ```

2. **槽位清理**：建议定期清理超时槽位，避免槽位泄漏
   - 可以添加定时任务每小时执行一次 `cleanup_stale_slots()`

3. **监控告警**：建议监控槽位使用率，如果长期满载可能需要优化或增加资源

4. **日志查看**：关键日志包含 `RunningHub slot` 关键词，便于排查问题
