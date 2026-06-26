# AI Tools 流水线步骤机制

## 概述

Pipeline Steps（流水线步骤）是 `ai_tools` 处理流程的扩展机制，支持在任务提交前和执行结束后插入可异步处理的子步骤。

两个核心阶段：
- **param_prepare**（参数预处理）：在任务提交到外部 API 之前，对输入数据进行预处理（如 Seedance 2.0 / 2.0 Fast / 2.0 Mini 视频/图片人脸遮盖）
- **before_finish**（结束前处理）：任务失败后，自动切换不同供应商重试

> **适配模型清单（单一事实来源）**：param_prepare 人脸遮盖适用的 Seedance 模型统一维护在 `config/unified_config.py::SEEDANCE_FACE_MASK_DRIVER_KEYS`，`server.py` 闸门与 `PipelineDriverFactory` 均查询该集合，新增模型只需在此追加一项。

## 状态机

```
                  [API 创建 ai_tool]
                         |
                         v
                   PENDING (0)
                    /         \
          [有 param_prepare]  [无步骤]
             步骤?               |
                |                v
                v          _submit_new_task()
      WAITING_PARAM_PREPARE (4)     |
                |                   v
      [所有步骤完成]         PROCESSING (1)
                |             /          \
                v      [成功]          [失败]
          PENDING (0)     |              |
                |         v              v
                |    COMPLETED (2)  [有 before_finish
                |                    步骤?]
                |                   /         \
                |            [有]             [无]
                |               |              |
                |               v              v
                |    WAITING_BEFORE_FINISH(5)  FAILED (-1)
                |               |
                |    [重试步骤选新供应商]
                |               |
                |               v
                +-------- PENDING (0)
                         (用新 implementation 重新提交)
```

### AI Tool 状态

| 状态值 | 名称 | 说明 |
|-------|------|------|
| 0 | PENDING | 待处理 |
| 1 | PROCESSING | 处理中（已提交到外部 API） |
| 2 | COMPLETED | 处理完成 |
| -1 | FAILED | 处理失败 |
| 3 | SYNC_QUEUED | 已提交到同步任务进程池 |
| **4** | **WAITING_PARAM_PREPARE** | 等待参数预处理步骤完成 |
| **5** | **WAITING_BEFORE_FINISH** | 等待结束前处理步骤完成（失败重试中） |

### Pipeline Step 状态

| 状态值 | 名称 | 说明 |
|-------|------|------|
| 0 | PENDING | 待处理 |
| 1 | PROCESSING | 处理中 |
| 2 | COMPLETED | 完成 |
| -1 | FAILED | 失败 |
| -2 | TIMEOUT | 超时 |

## 数据库表

### ai_tool_pipeline_steps

与 `ai_tools` 多对一关系，每个 ai_tool 可拥有多个流水线步骤。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| ai_tool_id | int | 关联 ai_tools.id |
| stage | varchar(32) | 阶段：`param_prepare` / `before_finish` |
| step_type | varchar(64) | 步骤类型：`face_mask` / `image_face_mask` / `implementation_retry` |
| step_order | int | 同阶段内执行顺序（0 起始） |
| status | tinyint | 步骤状态 |
| params | json | 步骤参数 |
| result_data | json | 步骤结果 |
| error_message | text | 失败原因 |
| async_task_id | int | 关联 async_tasks.id |
| retry_count | int | 重试次数 |
| next_retry_at | datetime | 下次重试时间 |
| max_retries | int | 最大重试次数（默认5） |

## 步骤类型

### face_mask（人脸遮盖）

用于 `param_prepare` 阶段，在 Seedance 2.0 等需要处理含人脸视频的场景中，先将视频中的人脸遮盖掉。

**触发条件**：Seedance 2.0 / 2.0 Fast / 2.0 Mini 任务类型 + `pipeline.seedance_face_mask_enabled=true` + 有 video_path 输入

**遮盖语义**：单帧 ComfyUI 工作流 `人脸识别_单帧.json` 不再在检测前 resize，YOLOv8 的 `BBOX Detector (combined)` 直接在原图上生成整图尺寸的 bbox 矩形 mask，再通过 `8x8` 黑色图像按 mask 拉伸合成回原图。遮盖区域以检测框 `x1/y1/x2/y2` 为基础，并使用 `dilation=128` 增加安全边距，补偿 YOLO face bbox 在侧脸、头发遮挡、扇子遮挡、局部置信度偏高时只框住人脸核心区域的问题；它不是 SEGS 裁剪图或人脸轮廓分割区域，避免出现纯黑背景里残留脸部裁剪图的结果。

**处理流程**：
1. FaceMaskPipelineDriver 调用 RunningHubFaceMaskDriver.submit_with_slot_management()
2. 创建 async_task 记录（implementation=RUNNINGHUB_FACE_MASK）
3. 槽位满时自动安排重试（指数退避：30s → 60s → 120s → 300s）
4. 后台任务 process_pending_async_task_submissions() 负责重试提交
5. process_runninghub_async_tasks() 轮询 async_task 状态
6. 完成后将遮盖后的视频 URL 写入 step.result_data
7. PipelineProcessor 将结果应用回 ai_tools.video_path

### image_face_mask（图片人脸遮盖）

用于 `param_prepare` 阶段，在 Seedance 2.0 / 2.0 Fast / 2.0 Mini 的图生视频任务提交前，对 `image_path` 和 `reference_images` 中的图片做人脸矩形黑块遮盖。

**触发条件**：Seedance 2.0 / 2.0 Fast / 2.0 Mini 任务类型 + `pipeline.seedance_face_mask_enabled=true` + 有 `image_path` 或 `reference_images` 输入

**配置开关**：`pipeline.seedance_face_mask_enabled`，默认 `true`，是 Seedance 人脸遮盖前置处理的**总开关**，同时控制图片（`image_face_mask`）和视频（`face_mask`）两种遮盖步骤。关闭后图片和视频的遮盖步骤均不创建，任务走普通生成流程。

**RunningHub 工作流**：调用 RunningHub AI App `2067560129192620033`，将输入图片上传后映射到节点 `3` 的 `image` 字段。工作流返回遮盖后的 png 结果，系统会先下载到本地 `upload/cache`，避免直接依赖 RunningHub 24 小时临时 URL。

**处理流程**：
1. ImageFaceMaskPipelineDriver 调用 RunningHubImageFaceMaskDriver.submit_with_slot_management()
2. 创建 async_task 记录（implementation=RUNNINGHUB_IMAGE_FACE_MASK）
3. 槽位满时自动安排重试（指数退避：30s → 60s → 120s → 300s）
4. process_runninghub_async_tasks() 轮询 RunningHub v2 任务状态
5. 完成后下载并缓存遮盖后的图片，将本地相对路径写入 step.result_data
6. PipelineProcessor 根据 step.params 中的 `field` 和 `index` 回写 `ai_tools.image_path` 或 `ai_tools.reference_images`

### implementation_retry（实现方重试）

用于 `before_finish` 阶段，任务失败后自动切换供应商重试。

**触发条件**：主任务失败 + 存在替代实现方

**处理流程**：
1. 从 UnifiedConfigRegistry 获取同任务类型的可用实现方列表
2. 排除已失败的实现方，选择替代实现方（最多 3 个）
3. 每个替代实现方创建一个 `implementation_retry` 步骤
4. 执行时更新 ai_tools.implementation 为目标实现方
5. 将 ai_tools 状态设回 PENDING，主流程自动重新提交
6. 如果槽位满，步骤会自动安排重试（由 PipelineProcessor 调度）

## 文件结构

```
model/
  ai_tool_pipeline_steps.py      # 数据库模型
task/
  pipeline_processor.py          # 编排器核心
  pipeline_drivers/
    __init__.py                  # 驱动工厂 + 步骤创建规则
    base_pipeline_driver.py      # 驱动抽象基类
    face_mask_driver.py          # 人脸遮盖驱动
    image_face_mask_driver.py    # 图片人脸遮盖驱动
    implementation_retry_driver.py  # 供应商重试驱动
```

## 调度

`scheduler.py` 中注册了 `process_pipeline_steps` 定时任务（每 10 秒），负责：
1. 查询所有 PROCESSING 状态的 pipeline steps
2. 检查关联 async_task 的状态
3. 推进步骤和 ai_tool 的状态

## 服务重启恢复

服务重启时，`_reset_orphan_processing_tasks()` 会将所有 WAITING_PARAM_PREPARE 和 WAITING_BEFORE_FINISH 状态的任务重置为 PENDING，让调度器重新检查 pipeline 步骤。

## 监控 SQL

```sql
-- 查看当前流水线步骤状态分布
SELECT stage, step_type, status, COUNT(*) as cnt
FROM ai_tool_pipeline_steps
GROUP BY stage, step_type, status;

-- 查看卡住的步骤（PROCESSING 超过 10 分钟）
SELECT id, ai_tool_id, stage, step_type, async_task_id, updated_at
FROM ai_tool_pipeline_steps
WHERE status = 1 AND updated_at < NOW() - INTERVAL 10 MINUTE;

-- 查看待重试的步骤
SELECT
    id,
    ai_tool_id,
    stage,
    step_type,
    retry_count,
    max_retries,
    next_retry_at
FROM ai_tool_pipeline_steps
WHERE status = 0
  AND next_retry_at IS NOT NULL
  AND next_retry_at <= NOW()
  AND retry_count < max_retries
ORDER BY next_retry_at;
```

## 相关文档

- [任务队列管理](./task_queue_management.md)
- [RunningHub 并发控制](./runninghub_concurrency_control.md)
- [统一配置系统](./unified_config_system.md)
