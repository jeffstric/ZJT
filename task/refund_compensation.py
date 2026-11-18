"""补退近期失败或取消、有扣费流水但没有 refund- 流水的任务。

调度进程里运行，允许同步 HTTP。无 transaction_id 的任务不进入本任务：
resolve_refund_amount 会退回静态价，可能给从未扣费的任务加钱。
"""
import logging
from datetime import date

from config.constant import (
    AI_TOOL_STATUS_CANCELLED,
    AI_TOOL_STATUS_FAILED,
    REFUND_COMPENSATION_BATCH_LIMIT,
    REFUND_COMPENSATION_LOOKBACK_DAYS,
    REFUND_COMPENSATION_RECONCILIATION_LOOKBACK_DAYS,
)
from model.computing_power_log import ComputingPowerLogModel
from model.database import execute_query
from utils.computing_power import REFUND_TXN_PREFIX

logger = logging.getLogger(__name__)

_CANDIDATE_SQL = """
    SELECT t.id
    FROM ai_tools t
    WHERE t.status IN (%s, %s)
      AND t.transaction_id IS NOT NULL
      AND t.transaction_id <> ''
      AND t.completed_time IS NOT NULL
      AND t.completed_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
      AND EXISTS (
          SELECT 1 FROM computing_power_log d
          WHERE d.transaction_id = t.transaction_id
            AND d.user_id = t.user_id
            AND d.behavior = 'deduct'
      )
      AND NOT EXISTS (
          SELECT 1 FROM computing_power_log r
          WHERE r.transaction_id = CONCAT(%s, t.transaction_id)
      )
    ORDER BY t.completed_time ASC
    LIMIT %s
"""

# 宽窗口未结算计数（对账告警用）：与 _CANDIDATE_SQL 同条件，去掉排序/分页换 COUNT
_STALE_COUNT_SQL = """
    SELECT COUNT(*) AS cnt
    FROM ai_tools t
    WHERE t.status IN (%s, %s)
      AND t.transaction_id IS NOT NULL
      AND t.transaction_id <> ''
      AND t.completed_time IS NOT NULL
      AND t.completed_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
      AND EXISTS (
          SELECT 1 FROM computing_power_log d
          WHERE d.transaction_id = t.transaction_id
            AND d.user_id = t.user_id
            AND d.behavior = 'deduct'
      )
      AND NOT EXISTS (
          SELECT 1 FROM computing_power_log r
          WHERE r.transaction_id = CONCAT(%s, t.transaction_id)
      )
"""


def find_refund_compensation_ids(limit: int = None) -> list:
    """返回需要补退的 ai_tools.id。查询失败时返回空列表，下个周期再试。"""
    batch = int(limit or REFUND_COMPENSATION_BATCH_LIMIT)
    try:
        rows = execute_query(
            _CANDIDATE_SQL,
            (
                AI_TOOL_STATUS_FAILED,
                AI_TOOL_STATUS_CANCELLED,
                REFUND_COMPENSATION_LOOKBACK_DAYS,
                REFUND_TXN_PREFIX,
                batch,
            ),
            fetch_all=True,
        )
    except Exception as e:
        logger.error(f"Refund compensation query failed: {e}")
        return []
    ids = []
    for row in rows or []:
        tool_id = row.get("id") if isinstance(row, dict) else None
        if type(tool_id) is int:
            ids.append(tool_id)
    return ids


# 每日对账节流：进程内记录上次告警日期，跨重启自然重置（最多每天多告警一次）
_reconciliation_last_alert_date = None


def reconcile_wide_window_once_per_day() -> None:
    """每日一次统计宽窗口（REFUND_COMPENSATION_RECONCILIATION_LOOKBACK_DAYS 天）内未结算数。

    lookback 窗口（REFUND_COMPENSATION_LOOKBACK_DAYS=7 天）会把长期未结算项静默
    甩出补偿范围——生产环境曾因此连续数日零日志、债务沉默不可见。这里兜底告警，
    保证债务始终可见。
    """
    global _reconciliation_last_alert_date
    today = date.today()
    if _reconciliation_last_alert_date == today:
        return
    _reconciliation_last_alert_date = today
    try:
        row = execute_query(
            _STALE_COUNT_SQL,
            (
                AI_TOOL_STATUS_FAILED,
                AI_TOOL_STATUS_CANCELLED,
                REFUND_COMPENSATION_RECONCILIATION_LOOKBACK_DAYS,
                REFUND_TXN_PREFIX,
            ),
            fetch_one=True,
        )
        count = int((row or {}).get("cnt") or 0) if isinstance(row, dict) else 0
        if count > 0:
            logger.warning(
                "Refund reconciliation: %s ai_tools still unsettled within %s days "
                "(outside the %s-day hourly batch window; export & review before manual settle)",
                count,
                REFUND_COMPENSATION_RECONCILIATION_LOOKBACK_DAYS,
                REFUND_COMPENSATION_LOOKBACK_DAYS,
            )
    except Exception as e:
        logger.error(f"Refund reconciliation query failed: {e}")


def compensate_missed_refunds(limit: int = None) -> int:
    """补退一批任务。返回实际退款成功的条数。"""
    from model import AIToolsModel
    from task.queued_cancel import clear_cancel_refund_pending_message
    from task.visual_task import _refund_computing_power

    reconcile_wide_window_once_per_day()

    succeeded = 0
    for tool_id in find_refund_compensation_ids(limit):
        try:
            tool = AIToolsModel.get_by_id(tool_id)
        except Exception as e:
            logger.error(f"Refund compensation load ai_tool {tool_id} failed: {e}")
            continue
        if tool is None:
            continue
        transaction_id = getattr(tool, "transaction_id", None)
        if not transaction_id:
            continue
        refund_id = f"{REFUND_TXN_PREFIX}{transaction_id}"
        if len(refund_id) > 100:
            logger.error(
                "Skip refund compensation for ai_tool %s: refund id longer than 100",
                tool_id,
            )
            continue
        try:
            deducted = ComputingPowerLogModel.get_deducted_power_by_transaction(
                tool.user_id, transaction_id,
            )
        except Exception as e:
            logger.error(f"Refund compensation deduct lookup {tool_id} failed: {e}")
            continue
        if not deducted:
            continue
        try:
            done = bool(_refund_computing_power(tool, "退款补偿"))
        except Exception as e:
            logger.error(f"Refund compensation for ai_tool {tool_id} failed: {e}")
            continue
        if not done:
            logger.error(f"Refund compensation for ai_tool {tool_id} not settled")
            continue
        clear_cancel_refund_pending_message(tool)
        succeeded += 1
        logger.info(f"Refund compensation settled ai_tool {tool_id}")
    return succeeded
