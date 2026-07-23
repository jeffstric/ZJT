# AI Tools 流水线步骤机制

## 概述

Pipeline Steps（流水线步骤）是 `ai_tools` 处理流程的扩展机制，支持在任务提交前和执行结束后插入可异步处理的子步骤。

两个核心阶段：
- **param_prepare**（参数预处理）：在任务提交到外部 API 之前，对输入数据进行预处理（如 Seedance 2.0 / 2.0 Fast / 2.0 Mini 视频/图片人脸遮盖）
- **before_finish**（结束前处理）：任务失败后，自动切换不同供应商重试

> **适配模型清单（单一事实来源）**：param_prepare 人脸遮盖适用的 Seedance 模型统一维护在 `config/unified_config.py::SEEDANCE_FACE_MASK_DRIVER_KEYS`，`server.py` 闸门与 `PipelineDriverFactory` 均查询该集合，新增模型只需在此追加一项。

> **用户开关与版本门（opt-in）**：人脸遮盖改为**用户显式勾选才生效（默认不勾选）**。`/api/ai-app-run-image` 新增表单参数 `enable_face_mask: bool = Form(False)`；`server.py` 的 `need_pipeline_steps` 闸门最终为 `is_seedance_face_mask AND enable_face_mask AND (NOT Edition.is_community()) AND runninghub_api_key AND has_any_param_prepare_input`。
> - **未勾选 / 社区版**：闸门为假 → 走 `AIToolsModel.create`（普通生成，**不创建任何步骤**，避免卡在 `WAITING_PARAM_PREPARE`）。
> - **勾选 + 商业版**：走 `AIToolsModel.create_with_pipeline_steps`（建 `face_mask` / `image_face_mask` 步骤）。
> - 版本判断 `NOT Edition.is_community()` **必须**在闸门内，不能仅依赖 `create_with_pipeline_steps` 内部判断，否则社区版会把 ai_tool 以 `WAITING_PARAM_PREPARE` 落库却不建步骤，导致任务永久卡死。
> - 前端通过 `/api/system/task-configs` 下发的每模型标志 `needs_face_mask`（= `key in SEEDANCE_FACE_MASK_DRIVER_KEYS`）显隐「是否处理人脸」选项；社区版下选项仍显示但置灰提示「商业版功能」。智能体（marketing-video）路径经 `video_preferences.enable_face_mask` 透传同一开关。

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
| step_type | varchar(64) | 步骤类型：`face_mask` / `image_face_mask` / `implementation_retry` / `storyboard_first_frame_grid_split` |
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

**触发条件**：Seedance 2.0 / 2.0 Fast / 2.0 Mini 任务类型 + 用户勾选 `enable_face_mask=true` + 商业版（非社区版）+ `pipeline.seedance_face_mask_enabled=true` + 有 video_path 输入

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

**触发条件**：Seedance 2.0 / 2.0 Fast / 2.0 Mini 任务类型 + 用户勾选 `enable_face_mask=true` + 商业版（非社区版）+ `pipeline.seedance_face_mask_enabled=true` + 有 `image_path` 或 `reference_images` 输入

**配置开关**：`pipeline.seedance_face_mask_enabled`，默认 `true`，是 Seedance 人脸遮盖前置处理的**总开关**（管理员级），同时控制图片（`image_face_mask`）和视频（`face_mask`）两种遮盖步骤。关闭后图片和视频的遮盖步骤均不创建，任务走普通生成流程。其上还有两层用户/版本级门：用户级 `enable_face_mask`（前端「是否处理人脸」勾选，默认不勾选，**opt-in**）与版本级 `NOT Edition.is_community()`（社区版禁止），三者同时满足才会创建步骤（见上文「用户开关与版本门」）。

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
2. 排除已经实际尝试过、已禁用或无法初始化的实现方，只选择优先级最高的 **1 个**替代实现方
3. 为该实现方创建唯一一个 `implementation_retry` 步骤；不会提前为后续实现方创建候选步骤
4. retry driver 先切换 `ai_tools.implementation` 并记录新的 implementation attempt，最后才把 `tasks.status` 改为 QUEUED
5. 主调度器只抓取 QUEUED 任务，因此抓到时 implementation 和 attempt 已经是新的供应商
6. 如果新供应商再次真实失败，再由失败入口按同样规则创建下一个唯一候选
7. 初始供应商之外最多尝试 3 个不同的备用供应商，即最多形成 `A → B → C → D`；达到上限或没有可用实现方后进入终态失败

步骤参数使用 `retry_mode=single_candidate_v1` 标识新模式，并记录 `retry_index`、`attempt_number`、`target_implementation` 与失败来源。升级前已经存在的多候选步骤仍兼容处理：只执行第一个，其余旧候选标记为 `legacy_multiple_candidates`，不会同时切换多个供应商。

**无锁顺序交接**：失败处理先将当前 attempt 标记失败，再把 `ai_tools/tasks` 设为 `WAITING_BEFORE_FINISH`，最后才创建唯一 PENDING 步骤；retry driver 先写入新 implementation 和 attempt，最后才把 `tasks` 设为 QUEUED。标准启动方式只运行一个 scheduler，两个 Job 各自 `max_instances=1`，因此不增加事务封装、应用锁或分布式锁。

**失败路径统一入口**：所有任务失败路径（driver 创建失败、提交失败、状态检查异常等）均通过 `_handle_task_failure()` 统一处理，由其调用 `handle_failure_with_retry()` 尝试切换供应商。无可用替代供应商时走终态失败 + 退费。

### storyboard_first_frame_grid_split（分镜首帧宫格拆分）

用于 `before_finish` 阶段，将分镜首帧宫格图（grid image）拆分为各场景的独立首帧并落库。

> **关联键说明**：该步骤类型通过 `params.grid_task_id`（= `grid_image_tasks.id` 主键）与宫格任务关联，**不依赖** `ai_tool_id == grid_image_tasks.project_id` 这一等式。原因是宫格图重试时 `_resubmit_image_request` 会新建一条 `ai_tools` 记录，`reset_for_retry` 把 `grid_image_tasks.project_id` 更新为新 `ai_tool_id`，导致 `project_id` 漂移；而 `grid_task_id` 主键在重试中保持稳定。因此 step 的查找（成功路径 dispatch）、失败回写、孤儿清理统一按 `params.grid_task_id` 关联。

**生命周期**：
1. 提交宫格 i2i 任务时（`mcp_tool.submit_grid_image_task`）**预建** PENDING 步骤，`params.grid_task_id` = 新建的 `grid_image_tasks.id`
2. 宫格图成功后（`_dispatch_storyboard_first_frame_grid_split`）按 `grid_task_id` 找到预建步骤，校准 `params`（补充重试后的最新宫格图数据），再 dispatch
3. 步骤被 `_is_grid_task_owned_step` 识别，**不**由全局 `process_pipeline_steps` 调度器执行，而由 `grid_image_task` 调度器主动 dispatch
4. 宫格图失败时（`_fail_pending_grid_split_step_for_task`）按 `grid_task_id` 将仍 PENDING 的步骤标记 FAILED
5. 孤儿兜底清理（`_cleanup_orphan_grid_split_steps`，每轮 grid 调度开头）按 `grid_task_id` JOIN `grid_image_tasks`，对已进入终态（含 COMPLETED 与各失败终态）但仍 PENDING 的孤儿步骤批量 FAILED

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
    storyboard_grid_split_driver.py  # 分镜首帧宫格拆分驱动
  grid_image_task.py             # 宫格任务调度（含 grid split step dispatch/fail/孤儿清理）
scripts/
  cleanup_stale_grid_split_steps.py  # 一次性清理僵尸 grid split step 的运维脚本
```

## 调度

`scheduler.py` 中注册了 `process_pipeline_steps` 定时任务（每 13 秒），负责：
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

-- 排查僵尸 storyboard grid split step（仍 PENDING 但宫格任务已进入终态）
-- 此类 step 会被全局调度器每 13s 反复 skip 刷日志，可用 scripts/cleanup_stale_grid_split_steps.py 清理
SELECT
    s.id AS step_id, s.ai_tool_id, s.created_at,
    CAST(JSON_UNQUOTE(JSON_EXTRACT(s.params, '$.grid_task_id')) AS UNSIGNED) AS grid_task_id,
    g.status AS grid_status
FROM ai_tool_pipeline_steps s
LEFT JOIN grid_image_tasks g
  ON g.id = CAST(JSON_UNQUOTE(JSON_EXTRACT(s.params, '$.grid_task_id')) AS UNSIGNED)
WHERE s.step_type = 'storyboard_first_frame_grid_split'
  AND s.stage = 'before_finish'
  AND s.status = 0;
```

## 相关文档

- [任务队列管理](./task_queue_management.md)
- [RunningHub 并发控制](./runninghub_concurrency_control.md)
- [统一配置系统](./unified_config_system.md)
