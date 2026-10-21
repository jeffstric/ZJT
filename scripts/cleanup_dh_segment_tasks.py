#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
一次性运维脚本：关闭开发环境残留的「旧分段数字人」任务。

背景
----
旧实现（sync_mode 全流水线）把各段音频路径写在 ai_tools.extra_config.dh_segments，
由驱动在一次 submit 调用里同步跑完整条流水线。新实现（compose_job）改成
「每段一条标准 ai_tools + compose_jobs 编排」，驱动里的 dh_segments 分支将在 P2 删除。

若删除分支前库里仍有 extra_config 含 dh_segments 且未到终态的任务，它们会被
调度器按**普通单段**路径重新提交——_resolve_duration 读到的 duration 是总时长
（>15 不在支持档位），回退 DEFAULT_DURATION=10，给上游提交一个错误任务。

本脚本用于在切换前把这些在途任务一次性关停：段级 ai_tools 置 FAILED、
tasks 调度行置 FAILED、按原扣费流水幂等退费。

判定条件
----
    extra_config LIKE '%dh_segments%' AND status IN (0, 1)

用法
----
    # 1. 默认 dry-run，只打印将被关闭的任务，不写库
    python scripts/cleanup_dh_segment_tasks.py

    # 2. 确认无误后真正执行（含退费）
    python scripts/cleanup_dh_segment_tasks.py --execute

    # 3. 只看退费不算账：--execute --skip-refund
    python scripts/cleanup_dh_segment_tasks.py --execute --skip-refund

回滚
----
被关闭的任务已退费，不建议回滚；如需重跑请由用户在前端重新提交。
"""
import argparse
import os
import sys

# 允许从仓库根目录直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.database import execute_query  # noqa: E402
from model import AIToolsModel, TasksModel  # noqa: E402
from config.constant import (  # noqa: E402
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_FAILED,
    TASK_STATUS_FAILED,
    TASK_TYPE_GENERATE_VIDEO,
)
from perseids_server.client import make_perseids_request  # noqa: E402
from utils.computing_power import (  # noqa: E402
    build_refund_transaction_id,
    is_already_refunded,
    resolve_refund_amount,
)

FAIL_REASON = "旧分段流水线任务已下线（compose_job 迁移），请重新提交"


def _find_inflight_segment_tasks():
    """查找旧分段链路在途任务（段路径写在 extra_config.dh_segments）。"""
    sql = """
        SELECT id, user_id, type, duration, status, transaction_id, project_id
        FROM ai_tools
        WHERE extra_config LIKE %s
          AND status IN (%s, %s)
        ORDER BY id ASC
    """
    return execute_query(
        sql, ('%dh_segments%', AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING), fetch_all=True
    ) or []


def _refund(ai_tool, skip_refund: bool) -> str:
    """按原扣费流水原额退回（refund-{原流水} 幂等）；返回结果描述。"""
    if skip_refund:
        return "skipped(退费已跳过)"
    if not getattr(ai_tool, 'transaction_id', None):
        return "skipped(无扣费流水)"
    try:
        if is_already_refunded(ai_tool):
            return "skipped(已退费)"
        amount = resolve_refund_amount(ai_tool)
        if not amount:
            return "skipped(无法解析退费金额)"
        success, message, response_data = make_perseids_request(
            endpoint='get_auth_token_by_user_id',
            method='POST',
            data={"user_id": ai_tool.user_id},
        )
        if not success:
            return f"failed(取token失败: {message})"
        headers = {'Authorization': f"Bearer {response_data['token']}"}
        success, message, _ = make_perseids_request(
            endpoint='user/calculate_computing_power',
            method='POST',
            headers=headers,
            data={
                "computing_power": amount,
                "behavior": "increase",
                "transaction_id": build_refund_transaction_id(ai_tool),
            },
        )
        return f"refunded({amount})" if success else f"failed({message})"
    except Exception as e:  # noqa: BLE001
        return f"failed({e})"


def main() -> int:
    parser = argparse.ArgumentParser(description="关闭开发环境残留的旧分段数字人任务")
    parser.add_argument("--execute", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument("--skip-refund", action="store_true", help="只置失败，不退费")
    args = parser.parse_args()

    rows = _find_inflight_segment_tasks()
    if not rows:
        print("没有需要清理的旧分段任务。")
        return 0

    print(f"命中 {len(rows)} 条旧分段任务：")
    for row in rows:
        print(f"  ai_tool={row['id']} user={row['user_id']} type={row['type']} "
              f"duration={row['duration']} status={row['status']} "
              f"txn={row.get('transaction_id')}")

    if not args.execute:
        print("\n[dry-run] 未写库。确认无误后加 --execute 执行。")
        return 0

    ok, refunded, failed = 0, 0, 0
    for row in rows:
        ai_tool_id = row['id']
        try:
            # 1) 调度行置失败，阻止调度器继续驱动
            #    tasks 表混存 generate_video / compose_job 两类行，task_id 可撞号，
            #    必须按 (task_type, task_id) 定位后走主键更新
            row = TasksModel.get_by_type_and_task_id(
                TASK_TYPE_GENERATE_VIDEO, ai_tool_id)
            affected = (
                TasksModel.update(row.id, status=TASK_STATUS_FAILED) if row else 0
            )
            # 2) 任务主记录置失败
            AIToolsModel.update(
                ai_tool_id,
                status=AI_TOOL_STATUS_FAILED,
                message=FAIL_REASON,
            )
            # 3) 退费（幂等）
            ai_tool = AIToolsModel.get_by_id(ai_tool_id)
            refund_result = _refund(ai_tool, args.skip_refund) if ai_tool else "skipped(记录缺失)"
            if refund_result.startswith("refunded"):
                refunded += 1
            print(f"  已关闭 ai_tool={ai_tool_id} tasks_rows={affected} 退费={refund_result}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  关闭失败 ai_tool={ai_tool_id}: {e}")

    print(f"\n完成：成功 {ok} / 退费 {refunded} / 失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
