# 场景多角度生图任务（location_multi_angle_task）

## 功能概述

为剧本世界观中的场景（location）基于主参考图生成多角度视角图片，生成结果写入场景 JSON 的
`reference_images` 暂存区。任务记录在 `location_multi_angle_tasks` 表，由 scheduler 进程通过
`process_pending_location_multi_angle_tasks` 轮询处理。

## 状态机：一次一个角度

`process_location_multi_angle_task` 是非阻塞状态机，每个调度周期只推进一个角度，避免长时间
阻塞调度线程：

1. **无等待中的 AI 任务** → 组装提示词（`<sks> {方向} eye-level shot medium shot`）提交当前角度到
   本机 `/api/image-edit`，记录 `ai_tool_task_id` 并等待下一周期；
2. **有等待中的 AI 任务** → 查 `ai_tools` 表状态：
   - `COMPLETED` → 下载图片落盘、写场景暂存区、推进 `current_angle_index`；
   - `FAILED` → 跳过该角度，推进 `current_angle_index`，重置重试计数；
   - 处理中 → 返回 `waiting`，等下一周期再查。

## 提交失败重试

提交 `/api/image-edit` 失败（响应 `status != submitted`、`submitted` 但 `project_ids` 为空、
请求异常等）时，由 `_handle_submit_failure` 处理：

- `current_angle_retry_count` 递增，错误信息写入 `error_message`，下一周期重试同一角度；
- 达到 `LOCATION_MULTI_ANGLE_SUBMIT_MAX_RETRY`（定义于 `config/constant.py`，默认 3）次后
  跳过该角度，`current_angle_index + 1`，重试计数清零。

错误信息提取顺序：`error` 字段 → `detail` 字段 → `'未知错误'`；`submitted` 但 `project_ids`
为空时固定报 `'未返回 project_id'`。

## 终态判定（_finalize_task）

`current_angle_index` 越过最后一个角度时，统一由 `_finalize_task` 判定终态：

| 产出 | 终态 | error_message |
|------|------|---------------|
| 零产出（全部角度失败） | `FAILED` | `所有角度生成失败，共完成 0/N 个` |
| 部分产出 | `COMPLETED` | `部分角度生成失败，共完成 M/N 个` |
| 全部产出 | `COMPLETED` | 无 |

已处于 `COMPLETED`/`FAILED` 终态的任务不会重复回写。

> 历史问题：零产出也曾被无条件置 `COMPLETED`，前端只能显示"任务完成但无图片"，
> 无法进入失败提示（2026-07 修复）。

## 相关文件

- `task/location_multi_angle_task.py` — 状态机、提交失败重试与终态判定
- `model/location_multi_angle_tasks.py` — `location_multi_angle_tasks` 表模型
- `tests/task/test_location_multi_angle_task.py` — 回归测试
- E2E mock 通道说明见 `docs/e2e_mock_implementation_plan.md` §5.7
