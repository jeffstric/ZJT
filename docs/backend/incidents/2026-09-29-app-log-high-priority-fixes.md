# 2026-09-29 app.log 三类高优先级报错修复记录

> 数据来源：生产 `logs/app.2026-09-29.log` 广度扫描（38 ERROR / 5206 WARNING）+ 追溯历史日志。修复分支：`develop_f934`（基于 origin/develop@45a61db0）。

## 概述

| # | 问题 | 影响 | 修复 |
|---|------|------|------|
| 1 | pipeline step 卡死：PROCESSING 且无 async_task_id 永不回收 | step 6759 自 09-14 起挂 15+ 天，日均 ~6600 条 WARNING（占全天 WARNING 的 84%），所属 ai_tool 48161 param_prepare 阶段永久挂起 | 调度器每轮开始时回收超时卡死步骤，走正常失败链路（终结 + 退款） |
| 2 | grid_image_task 轮询 401 无限重试 | 任务 1337_0_50937 的 auth_token 快照失效后连续 401 共 105 次（每 10s 一条 WARNING），重试提交同样 401，用户任务白白终态失败 | 连续认证失败达阈值即终止任务（FAILED 终态 + 联动下游） |
| 3 | 参考图 404 报错为"服务异常" | 任务 50937/50938 引用已清理的 `upload/cache/2026-08-10/...png`（本地不存在 + 远程 404），走 Unexpected exception：误触 Sentry UNEXPECTED_EXCEPTION，用户看到"服务异常，请联系技术支持"，重试必然失败 | 404/410 转 `ImageExpiredError` → USER 错误，明确提示重新上传，不再触发系统告警 |

## 问题 1：pipeline step 卡死（step 6759）

### 证据链

- `Step 6759 is PROCESSING but has no async_task_id, step_type=h3_prompt_optimize`：09-14 起每天 ~6600 条，09-29 至 15:50 已 4363 条（每 13s 一条，与调度器 `process_all_pending_steps` 周期一致）。
- 归属 ai_tool 48161，param_prepare 阶段；`Pipeline stage param_prepare for ai_tool 48161: total=1, completed=0, pending=1, failed=0` 全天不变。

### 根因

`dispatch_step` 先把步骤置为 PROCESSING（`pipeline_processor.py`），执行后才写回 async_task_id；若进程在两者之间异常退出（如 2026-09-12 FD 耗尽事故期间），该步骤成为**永久孤儿**（PROCESSING + async_task_id NULL）。`_process_single_step` 对此类步骤只 `logger.warning` 后 return，没有任何超时回收机制——调度器每轮都扫到、每轮都告警，步骤永不转终态。

### 修复

- `config/constant.py`：新增 `PipelineConfig.STUCK_PROCESSING_WITHOUT_ASYNC_TASK_TIMEOUT_SECONDS = 3600`、`STUCK_PROCESSING_RECOVER_LIMIT = 20`。
- `model/ai_tool_pipeline_steps.py`：新增
  - `get_stuck_processing_steps_without_async_task(timeout_seconds, limit)`——超时判定在 SQL 层 `NOW() - INTERVAL`，**不受应用/数据库时区差异影响**（走 `idx_status_updated` 索引）；
  - `fail_processing_steps_by_ids(step_ids, error_message)`——只更新 status=PROCESSING 的行，幂等。
- `task/pipeline_processor.py`：
  - `process_all_pending_steps` 第 0 步调用新增的 `_recover_stuck_processing_steps()`（无卡死时开销为一次走索引的查询）；
  - 回收只把步骤置 FAILED，**不**调用 `_check_ai_tool_stage_completion` 抢跑推进 ai_tool——该函数的失败分支只改 ai_tools 表（不更新 tasks、不退款），会把 ai_tool 置 FAILED 使 `visual_task._check_pipeline_stage` 的入口分支（要求 WAITING_PARAM_PREPARE/WAITING_BEFORE_FINISH）永远失配，退款与 tasks 终结退化为 30 次 max-retry 指数退避兜底。终态化留给 visual_task：其 5s 轮询内 `_check_pipeline_stage` 检测到步骤 FAILED 即一步完成 ai_tool/tasks FAILED + **退款**（所有带 pipeline 步骤的任务均为 TASK_TYPE_GENERATE_VIDEO，在 visual_task 轮询范围内，闭环完整）；
  - `_process_single_step` 的 WARNING 增加 `stuck_seconds` 字段，便于观察回收前进度。

### 存量数据

部署后 1 小时内，step 6759 会被自动回收，无需手工修数。若希望立即回收，可由 DBA 执行（参考，非必须）：

```sql
UPDATE ai_tool_pipeline_steps
SET status = -1, error_message = '步骤卡死回收：部署前存量孤儿'
WHERE status = 1 AND async_task_id IS NULL
  AND updated_at < NOW() - INTERVAL 3600 SECOND;
```

> 注意：仅置步骤状态即可，ai_tool/tasks 的终结与退款由调度链路自动完成，**不要**直接改 ai_tools/tasks 表。

## 问题 2：grid_image_task 轮询 401 无限重试

### 证据链

```
15:18:34~15:35:54 - task.grid_image_task - WARNING - 轮询ComfyUI失败: 1337_0_50937,
  错误: 401 Client Error: Unauthorized for url: http://ailive.perseids.cn/api/get-status/50937?auth_token=4508...
（连续 105 次，每 10s 一条）
15:35:54 - task.grid_image_task - ERROR - 任务 1337_0_50938 重试提交失败: Client error '401 Unauthorized'
15:35:54 - task.grid_image_task - ERROR - 任务 1337_0_50938 重试提交失败，标记为终态失败
```

### 根因

`grid_image_tasks.auth_token` 是**任务创建时的快照**。用户 token 失效/被顶号（单会话策略：另处登录即删旧 token，见 `docs/backend/auth_token_401_semantics.md`）后：

1. 轮询 `get-status` 必然 401，`except requests.RequestException` 分支只告警不终止（当成网络抖动"继续重试"），每 10s 一条 WARNING 无限刷；
2. 自动重试提交 `_resubmit_image_request` 同样用旧 token，401 → 任务终态失败——**用户任务白白失败**，且期间无任何有效告警。

### 修复

- `config/constant.py`：`GridConfig.AUTH_FAILURE_TERMINATION_LIMIT = 3`（3 次 × 10s ≈ 30s，足以排除 ComfyUI 网关瞬时 401 误伤）。
- `task/grid_image_task.py`：
  - 新增模块级连续计数 `_auth_failure_streaks`（进程内存态，重启重新累计可接受）；
  - 新增 `_is_auth_failure()`：只认 HTTP 401/403（网络错误/5xx/404 不算，保持原"继续重试"语义）；
  - 轮询成功清零计数；非认证异常清零（streak 语义为"连续"）；
  - 连续达阈值 → `_terminate_task_for_auth_failure()`：状态置 FAILED（error_message 注明认证失败）+ 状态文件 + 分镜批次 item 联动（复用既有终态路径）；
  - 任务终态（成功/超时/失败）时清理计数，防 dict 残留。

### 遗留（未在本次修复）

- `_resubmit_image_request` 仍用任务快照 token。根因侧的改进方向：重试提交前按 `task.user_id` 查询 `user_tokens` 表获取有效 token（涉及用户会话语义，另行评估）。
- ComfyUI 侧 `get-status`/`text-to-image` 对已失效 token 直接 401 是正确行为，不改。

## 问题 3：参考图 404 误报"服务异常"

### 证据链

```
15:19:44 - gpt_image_common_site1_v1 - WARNING - 映射的本地文件不存在: .../upload/cache/2026-08-10/25547_...png
15:19:44 - gpt_image_common_site1_v1 - ERROR - 准备图片文件失败: ... 404 Client Error
15:19:44 - gpt_image_common_site1_v1 - ERROR - Unexpected exception in GPT Image 2 submit_task: 404 ...
15:19:44 - utils.sentry_util - INFO - Alert sent to Sentry: UNEXPECTED_EXCEPTION
15:19:44 - task.sync_task_executor - ERROR - [SyncTask] Task 50937 failed: 服务异常，请联系技术支持
```

任务 50937/50938（同一用户 1337）连续两次失败，触发两次算力退款。

### 根因

资产/任务参数引用了 `upload/cache/2026-08-10/` 的历史缓存图，该文件已被定期清理（本地映射不存在 → 远程下载 404）。`_prepare_image_file` 的 404 走通用 `raise_for_status` → `Unexpected exception` 分支：触发 Sentry 系统告警 + 用户看到笼统的"服务异常，请联系技术支持"。**重试无法自愈**（源文件已不存在），属于应直接告知用户的输入问题。

### 修复

`task/visual_drivers/gpt_image_common_v1_driver.py`（GptImageCommonV1Driver 全家族 Site0-5 / 2.5 变体共用）：

- `_prepare_image_file`（multipart 路径）与 `_download_image_as_base64`（base64 路径）下载遇 **404/410** → 抛 `ImageExpiredError("参考图片已失效（原文件可能已被清理），请重新上传或更换参考图后重试")`；
- `submit_task` 既有 `except ImageExpiredError` 分支将其转为 `error_type=USER` 返回（复用图床签名过期同款通道，见 `docs/backend/image_url_expiry_refresh.md`），**不触发** Sentry UNEXPECTED_EXCEPTION；
- 5xx 等其他状态码维持原 HTTPError 语义（真正的系统故障仍走系统告警）。

### 遗留（未在本次修复）

`upload/cache` 清理策略与业务引用生命周期不一致的根治方案（清理前校验资产引用 / 被引用文件永久保留）影响面大，另行立项。

## 测试

新增 3 个测试文件共 17 个用例，全部通过：

- `tests/task/test_pipeline_stuck_step_recovery.py`（5）：回收链路 / **不抢跑终态化（回归断言 `_check_ai_tool_stage_completion` 不被调用）** / 无卡死不写 / SQL 参数与时区无关 / 幂等语义 / 告警不改状态
- `tests/task/test_grid_image_auth_failure.py`（7）：401/403 识别 / 终态写入与联动 / 计数清理 / 单次 401 不终止 / 非认证错误重置计数
- `tests/drivers/test_gpt_image_expired_reference.py`（5）：404/410 → ImageExpiredError / 5xx 保持原语义 / submit_task 返 USER 错误且不触发 Sentry

存量相关测试（pipeline / grid / gpt driver / model，97 个）全部通过，无回归。
