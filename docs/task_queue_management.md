# 任务队列管理机制

## 概述

本文档说明任务队列的管理机制，包括任务重试、过期处理和丢弃策略。

## 配置说明

在 `config.yml` 中配置任务队列管理参数：

```yaml
task_queue:
  max_retry_count: 30  # 最大重试次数，超过后任务将被标记为失败
  task_expire_days: 7  # 任务过期天数，创建后超过此天数的任务将被自动失败
  enable_expire_check: true  # 是否启用任务过期检查
```

### 配置参数说明

- **max_retry_count**: 任务失败后的最大重试次数
  - 默认值：30
  - 当任务重试次数达到此值时，任务将被标记为失败（status=-1）
  - 适用于所有任务类型（视频生成、音频生成等）
  - 会自动退还算力并释放资源

- **task_expire_days**: 任务过期天数
  - 默认值：7天
  - 从任务创建时间（created_at）开始计算
  - 超过此天数的任务将被自动标记为失败

- **enable_expire_check**: 是否启用过期检查
  - 默认值：true
  - 设置为 false 可以禁用任务过期检查

## 任务处理流程

### 1. 任务查询

系统每隔固定时间（视频任务11秒，音频任务7秒）查询待处理任务：

```python
# 查询状态为 0（队列中）或 1（处理中）的任务
# 且 next_trigger <= NOW() 的任务
tasks = TasksModel.list_by_type_and_status(task_type, status_list=[0, 1])
```

### 2. 任务过期检查

在处理每个任务前，首先检查是否过期：

```python
if _check_task_expiration(task):
    # 标记任务为失败
    TasksModel.update_by_task_id(task.task_id, status=-1)
    AIToolsModel.update(task.task_id, status=-1, message="任务已过期")
```

**过期判断逻辑**：
- 计算任务年龄：`task_age = datetime.now() - task.created_at`
- 如果 `task_age.days >= TASK_EXPIRE_DAYS`，则任务过期

### 3. 重试次数检查

检查任务是否超过最大重试次数：

```python
if _check_max_retry_exceeded(task):
    # 标记任务为失败
    TasksModel.update_by_task_id(task.task_id, status=-1)
    AIToolsModel.update(task.task_id, status=-1, message=f"超过最大重试次数({MAX_RETRY_COUNT})")
    
    # 退还算力
    # 释放 RunningHub 槽位
```

**重试判断逻辑**：
- 如果 `task.try_count >= MAX_RETRY_COUNT`，则标记为失败

**自动处理**：
- 标记任务为失败状态（status=-1）
- 自动退还用户算力
- 释放 RunningHub 槽位（如适用）

### 4. 任务处理

通过过期和重试检查后，执行实际的任务处理逻辑。

### 5. 失败重试

任务处理失败时，增加重试计数并设置下次触发时间：

```python
new_try_count = (task.try_count or 0) + 1
delay_seconds = calculate_next_retry_delay(new_try_count)
next_trigger = datetime.now() + timedelta(seconds=delay_seconds)
```

**重试延迟策略**（指数退避）：
- 基础延迟：3秒
- 延迟计算：`delay = 3 * (2 ^ (try_count - 1))`
- 最大延迟：360秒（6分钟）

| 重试次数 | 延迟时间 |
|---------|---------|
| 1       | 3秒     |
| 2       | 6秒     |
| 3       | 12秒    |
| 4       | 24秒    |
| 5       | 48秒    |
| 6       | 96秒    |
| 7       | 192秒   |
| 8+      | 360秒   |

## 任务状态说明

- **status = 0**: 队列中（待处理）
- **status = 1**: 处理中
- **status = 2**: 处理完成（成功）
- **status = -1**: 处理失败

## 日志输出

系统会输出详细的任务处理日志：

```
2026-01-29 20:00:00 - task.video_task - INFO - Found 5 tasks to process for type: generate_video
2026-01-29 20:00:00 - task.video_task - INFO - Start processing task: task_id=4495, table_id=123, status=0, try_count=5
2026-01-29 20:00:00 - task.video_task - WARNING - Task 4495 expired (created 8 days ago)
2026-01-29 20:00:00 - task.video_task - INFO - Task 4495 marked as expired
2026-01-29 20:00:00 - task.video_task - INFO - Summary: processed=4, succeeded=3, delayed=0, expired=1
```

## 特殊处理

### RunningHub 任务

对于 RunningHub 任务（type=10 LTX2.0, type=11 Wan2.2），在标记为过期或失败时会自动释放槽位：

```python
if ai_tool.type in [10, 11]:
    if ai_tool.project_id:
        RunningHubSlotsModel.release_slot_by_project_id(ai_tool.project_id)
    else:
        RunningHubSlotsModel.release_slot_by_task_table_id(task.id)
```

### 队列已满错误

当 RunningHub 返回 `TASK_QUEUE_MAXED` 错误时：
- 延迟60秒后重试
- 不增加重试计数（因为这不是任务本身的问题）

## 监控建议

### 1. 监控过期任务数量

定期检查被标记为过期的任务数量：

```sql
SELECT COUNT(*) FROM ai_tools 
WHERE status = -1 
AND message = '任务已过期'
AND DATE(update_time) = CURDATE();
```

### 2. 监控高重试次数任务

检查重试次数较高的任务：

```sql
SELECT task_id, try_count, status, next_trigger 
FROM tasks 
WHERE try_count >= 20 
ORDER BY try_count DESC;
```

### 3. 监控长时间未完成任务

检查创建时间较早但仍未完成的任务：

```sql
SELECT t.task_id, t.try_count, t.status, t.created_at, 
       DATEDIFF(NOW(), t.created_at) as days_old
FROM tasks t
WHERE t.status IN (0, 1)
AND DATEDIFF(NOW(), t.created_at) >= 3
ORDER BY t.created_at ASC;
```

## 故障排查

### 问题：任务长时间未处理

**可能原因**：
1. `next_trigger` 被设置到很久之后
2. 任务重试次数过多，延迟时间很长
3. 接口改动导致任务无法成功

**排查步骤**：
1. 检查任务的 `try_count` 和 `next_trigger`
2. 查看任务处理日志，确认失败原因
3. 如果是接口改动，需要手动清理或修复旧任务

### 问题：任务被意外标记为过期

**可能原因**：
1. `task_expire_days` 配置过短
2. 任务创建后长时间未被处理

**解决方案**：
1. 调整 `task_expire_days` 配置
2. 检查任务处理器是否正常运行
3. 检查是否有大量任务积压

## 最佳实践

1. **合理设置过期时间**：根据业务需求设置 `task_expire_days`，建议不少于3天
2. **监控重试次数**：定期检查高重试次数的任务，及时发现问题
3. **日志分析**：定期分析任务处理日志，了解任务失败原因
4. **接口变更**：接口改动后，及时清理或修复不兼容的旧任务
5. **容量规划**：根据任务量和处理速度，合理配置 RunningHub 槽位数量

## 相关文档

- [RunningHub 并发控制](./runninghub_concurrency_control.md)
- [测试模式指南](./test_mode_guide.md)
