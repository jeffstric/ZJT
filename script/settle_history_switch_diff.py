#!/usr/bin/env python3
"""历史「贵扣便宜用」任务差价补偿脚本（一次性审计 + 补偿）

背景：任务按供应商A价格扣费、失败切换到供应商B后成功（旧机制不退差价）。
新机制（settle_task_success_diff）只对增量生效；本脚本补偿历史任务。

口径（与 utils/computing_power.py: settle_task_success_diff 同源）：
  - 仅处理 status=2（COMPLETED）且发生过供应商切换（attempt>=2）的任务
  - 实扣 = ai_tools.transaction_id 关联扣费流水原额
  - 实际价 = 按「当前价格表 + 最终 implementation + duration + context」重算
    （⚠️ 价格热更新过，历史任务按当前价估算，清单会标注）
  - 只退不补：diff = 实扣 - 实际价 > 0 时补偿，diff < 0 历史不追收
  - 幂等：已存在 diff-refund-{原流水} 的跳过，可重复执行
  - 发放复用 settle_task_success_diff（受 billing.settle_diff_enabled 开关控制，
    补偿前请确认开关开启）

用法：
  干跑（默认，只输出清单）：
    comfyui_env=prod python script/settle_history_switch_diff.py
  实际发放补偿：
    comfyui_env=prod python script/settle_history_switch_diff.py --execute
  可选过滤：
    --user 1534          仅处理指定用户
    --task 28928         仅处理指定任务
"""
import argparse
import os
import sys

# 项目根目录加入 sys.path（脚本直击运行场景）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import logging  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('settle_history_diff')


def main():
    parser = argparse.ArgumentParser(description='历史供应商切换差价补偿（只退不补）')
    parser.add_argument('--execute', action='store_true', help='实际发放补偿（默认干跑仅输出清单）')
    parser.add_argument('--user', type=int, default=None, help='仅处理指定用户')
    parser.add_argument('--task', type=int, default=None, help='仅处理指定任务')
    args = parser.parse_args()

    from model.database import execute_query
    from model.ai_tools import AIToolsModel
    from model.computing_power_log import ComputingPowerLogModel
    from model.implementation_attempts import ImplementationAttemptModel
    from utils.computing_power import (
        settle_task_success_diff,
        _recalculate_task_power,
        DIFF_REFUND_TXN_PREFIX,
    )
    from config.constant import AI_TOOL_STATUS_COMPLETED

    # 1. 候选任务：成功 + 切换过 + 有扣费流水
    sql = """
        SELECT a.id, a.user_id, a.type, d.computing_power AS deducted
        FROM ai_tools a
        JOIN computing_power_log d
          ON d.transaction_id = a.transaction_id AND d.behavior = 'deduct'
        WHERE a.status = %s
          AND EXISTS (SELECT 1 FROM implementation_attempts ia
                      WHERE ia.ai_tool_id = a.id AND ia.attempt_number >= 2)
    """
    params = [AI_TOOL_STATUS_COMPLETED]
    if args.user is not None:
        sql += " AND a.user_id = %s"
        params.append(args.user)
    if args.task is not None:
        sql += " AND a.id = %s"
        params.append(args.task)

    rows = execute_query(sql, tuple(params), fetch_all=True) or []
    logger.info("候选任务（成功且切换过）: %d 个", len(rows))

    to_settle = []
    skipped_no_diff = skipped_undercharge = skipped_idempotent = skipped_err = 0
    for row in rows:
        task_id, user_id = row['id'], row['user_id']
        try:
            ai_tool = AIToolsModel.get_by_id(task_id)
            if not ai_tool or not ai_tool.transaction_id:
                skipped_err += 1
                continue

            # 幂等：已补偿过跳过
            if ComputingPowerLogModel.check_transaction_exists(
                    f"{DIFF_REFUND_TXN_PREFIX}{ai_tool.transaction_id}"):
                skipped_idempotent += 1
                continue

            actual = _recalculate_task_power(ai_tool, ai_tool.type, user_id)
            if not actual:
                skipped_err += 1
                continue

            diff = row['deducted'] - actual
            if diff == 0:
                skipped_no_diff += 1
                continue
            if diff < 0:
                # 历史少扣不追收（口径：只退不补）
                skipped_undercharge += 1
                continue

            to_settle.append({
                'task': task_id, 'user': user_id, 'type': ai_tool.type,
                'deducted': row['deducted'], 'actual': actual, 'diff': diff,
                'ai_tool': ai_tool,
            })
        except Exception as e:
            skipped_err += 1
            logger.warning("task %s 评估失败: %s", task_id, e)

    # 2. 输出清单
    print("\n===== 差价补偿清单（按当前价格表估算，只退不补） =====")
    print(f"{'任务':>8} {'用户':>8} {'类型':>6} {'实扣':>8} {'实际价':>8} {'应退':>8}")
    total = 0
    for item in to_settle:
        print(f"{item['task']:>8} {item['user']:>8} {item['type']:>6} "
              f"{item['deducted']:>8} {item['actual']:>8} {item['diff']:>8}")
        total += item['diff']
    print("-" * 52)
    print(f"合计应退: {total} 分 / {len(to_settle)} 笔")
    print(f"跳过: 无差价 {skipped_no_diff}, 历史少扣不追收 {skipped_undercharge}, "
          f"已补偿过 {skipped_idempotent}, 评估失败 {skipped_err}")

    if not args.execute:
        print("\n[干跑] 未发放。确认清单后加 --execute 实际发放。")
        return

    # 3. 实际发放（复用 settle_task_success_diff，其内部自带幂等与异常保护）
    print("\n===== 发放 =====")
    ok = fail = 0
    for item in to_settle:
        result = settle_task_success_diff(item['ai_tool'])
        if result is not None and result > 0:
            ok += 1
            logger.info("task %s 补偿 %s 分 ✓", item['task'], result)
        else:
            fail += 1
            logger.error("task %s 补偿失败（见上方日志）", item['task'])
    print(f"发放完成: 成功 {ok}, 失败 {fail}")


if __name__ == '__main__':
    main()
