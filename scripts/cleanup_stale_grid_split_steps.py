#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
一次性运维脚本：清理僵尸 storyboard_first_frame_grid_split pipeline step。

背景
----
宫格图重试时 _resubmit_image_request 会新建 ai_tool，reset_for_retry 把
grid_image_tasks.project_id 更新为新 ai_tool_id，但预建 step 的 ai_tool_id 保持旧值，
导致 step.ai_tool_id 与 grid.project_id 错位。成功/失败/孤儿清理三条路径都按
project_id==ai_tool_id 关联，因而全部失效，预建 step 永久卡在 PENDING，
被全局调度器每 13s 反复 skip 刷日志。

代码层修复已改为按 params.grid_task_id（grid 主键，稳定）关联，本脚本用于一次性收敛
修复前已积累的存量僵尸 step，使其立即停止刷日志。

孤儿判定
----
step 仍 PENDING，且按 params.grid_task_id 关联的 grid_image_tasks 已进入终态
（COMPLETED / FAILED / TIMEOUT / DOWNLOAD_FAILED / CANCELLED）。
若 grid 不存在或仍 QUEUED/PROCESSING（可能尚在处理），则跳过不动。

用法
----
    # 1. 默认 dry-run，只打印将被清理的 step，不写库
    python scripts/cleanup_stale_grid_split_steps.py

    # 2. 确认无误后加 --execute 真正标记 FAILED
    python scripts/cleanup_stale_grid_split_steps.py --execute

回滚
----
若误清理，可将对应 step 的 status 改回 0 (PENDING)：
    UPDATE ai_tool_pipeline_steps SET status = 0 WHERE id IN (...);
注意：被清理的 step 都是僵尸（其业务已由兄弟 step 完成或 grid 已失败），回滚一般无必要。
"""
import argparse
import json
import os
import sys

# 允许从仓库根目录直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.database import execute_query, execute_update  # noqa: E402
from model.ai_tool_pipeline_steps import (  # noqa: E402
    PipelineStepModel,
    PipelineStepStatus,
    PipelineStepType,
    PipelineStage,
)
from config.constant import GridImageTaskStatus  # noqa: E402

# grid 已进入终态的状态集合（含成功与失败）
GRID_TERMINAL_STATUSES = (
    GridImageTaskStatus.COMPLETED,
    GridImageTaskStatus.FAILED,
    GridImageTaskStatus.TIMEOUT,
    GridImageTaskStatus.DOWNLOAD_FAILED,
    GridImageTaskStatus.CANCELLED,
)

# grid 状态值 -> 可读名称，用于报告
GRID_STATUS_NAME = {
    GridImageTaskStatus.QUEUED: "QUEUED",
    GridImageTaskStatus.PROCESSING: "PROCESSING",
    GridImageTaskStatus.COMPLETED: "COMPLETED",
    GridImageTaskStatus.FAILED: "FAILED",
    GridImageTaskStatus.TIMEOUT: "TIMEOUT",
    GridImageTaskStatus.DOWNLOAD_FAILED: "DOWNLOAD_FAILED",
    GridImageTaskStatus.CANCELLED: "CANCELLED",
}

GRID_STATUS_NAMES_STR = ", ".join(GRID_STATUS_NAME[s] for s in GRID_TERMINAL_STATUSES)


def fetch_stale_steps():
    """
    查询所有 PENDING 的 grid split step，并 LEFT JOIN grid_image_tasks 取其状态。
    返回 [(step_id, ai_tool_id, grid_task_id, grid_status, created_at), ...]。
    """
    sql = """
        SELECT
            s.id AS step_id,
            s.ai_tool_id,
            CAST(JSON_UNQUOTE(JSON_EXTRACT(s.params, '$.grid_task_id')) AS UNSIGNED) AS grid_task_id,
            g.status AS grid_status,
            s.created_at
        FROM ai_tool_pipeline_steps s
        LEFT JOIN grid_image_tasks g
          ON g.id = CAST(JSON_UNQUOTE(JSON_EXTRACT(s.params, '$.grid_task_id')) AS UNSIGNED)
        WHERE s.step_type = %s
          AND s.stage = %s
          AND s.status = %s
        ORDER BY s.id ASC
    """
    return execute_query(sql, (
        PipelineStepType.STORYBOARD_FIRST_FRAME_GRID_SPLIT,
        PipelineStage.BEFORE_FINISH,
        PipelineStepStatus.PENDING,
    ), fetch_all=True) or []


def main():
    parser = argparse.ArgumentParser(description="清理僵尸 storyboard grid split pipeline step")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="真正执行清理（默认 dry-run，只打印）",
    )
    args = parser.parse_args()

    rows = fetch_stale_steps()
    print(f"[cleanup] 发现 {len(rows)} 个 PENDING 的 storyboard grid split step")

    to_fail = []      # 待标记 FAILED 的 step（grid 已终态）
    skipped = []      # 跳过（grid 不存在或仍 QUEUED/PROCESSING）
    for row in rows:
        grid_status = row.get("grid_status")
        grid_task_id = row.get("grid_task_id")
        status_name = GRID_STATUS_NAME.get(grid_status, f"UNKNOWN({grid_status})")
        if grid_status in GRID_TERMINAL_STATUSES:
            to_fail.append(row)
            print(
                f"  [将清理] step_id={row['step_id']} ai_tool_id={row['ai_tool_id']} "
                f"grid_task_id={grid_task_id} grid_status={status_name} created_at={row['created_at']}"
            )
        else:
            skipped.append(row)
            print(
                f"  [跳过  ] step_id={row['step_id']} ai_tool_id={row['ai_tool_id']} "
                f"grid_task_id={grid_task_id} grid_status={status_name}（非终态或 grid 不存在，暂不动）"
            )

    print(
        f"\n[cleanup] 汇总：待清理 {len(to_fail)} 个，跳过 {len(skipped)} 个。"
        f"终态判定: [{GRID_STATUS_NAMES_STR}]"
    )

    if not to_fail:
        print("[cleanup] 无需清理，退出。")
        return

    if not args.execute:
        print("[cleanup] 当前为 dry-run 模式，未写库。确认无误后加 --execute 执行清理。")
        return

    step_ids = [r["step_id"] for r in to_fail]
    affected = PipelineStepModel.fail_steps_by_ids(
        step_ids,
        error_message="存量僵尸 step 清理：宫格任务已进入终态，绑定 step 由本脚本标记为 FAILED",
    )
    print(f"[cleanup] 已标记 {affected} 个 step 为 FAILED: ids={step_ids}")


if __name__ == "__main__":
    main()
