#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RunningHub 槽位对账回收守护（reconciliation reclaimer）。

职责：周期性核对 runninghub_slots 中活跃槽位（status=1, source='task'）与其
关联任务（ai_tools，task_id = ai_tools.id）的真实状态，回收「任务已终态但
槽位未释放」的残留槽位，防止并发容量被永久蚕食。

⚠️ 设计约束：本模块**不感知任何具体业务动作**（提交/取消/重试等）。
回收判定只依赖任务系统的基础概念——「任务是否处于活跃状态」：

  活跃 = ai_tools.status IN (PENDING, PROCESSING, SYNC_QUEUED,
                             WAITING_PARAM_PREPARE, WAITING_BEFORE_FINISH,
                             DOWNLOADING)
  终态 = 其余一切状态值（含未来可能新增的任何终态）

因此：无论残留槽位由哪条路径产生（现状或未来新增的终态写入点遗漏释放），
只要任务落终态且超过宽限期，槽位都会被回收——本模块是槽位生命周期的
**兜底对账**，与各业务路径自身的即时释放（成功/失败/过期/超限/拥堵等
已有的 release 调用）互补，不替代。

防误回收设计（守护绝不能回收进行中任务的槽位）：
  1. 活跃状态一律跳过；
  2. 终态但 completed_time 距今不足宽限期（默认 600s）的跳过——终态刚落库时
     调度器可能仍持有该槽在向上游提交（在途秒级窗口），立即回收会导致
     提交成功后无槽可记、并发超发；宽限期内由业务路径自身的释放负责；
  3. 终态但 completed_time 为 NULL 的脏数据跳过并告警（保守优先，人工排查）；
  4. ai_tools 记录已不存在（极端不一致）→ 直接回收并告警。

范围说明：只对账 source='task'（视频任务链路）。source='async'（音频、
人脸遮盖等）的 task_id 语义不同（指向 async_tasks.id），不在此处理。
"""
import logging
from typing import List

from config.constant import (
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_SYNC_QUEUED,
    AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
    AI_TOOL_STATUS_WAITING_BEFORE_FINISH,
    AI_TOOL_STATUS_DOWNLOADING,
)
from config.config_util import get_dynamic_config_value
from model.database import execute_query
from model.runninghub_slots import RunningHubSlot, RunningHubSlotsModel

logger = logging.getLogger(__name__)

# 任务活跃状态集合（调度器正在处理的状态）。凡不在此集合内的状态一律视为
# 终态——这是「不感知业务动作」的关键：新增任何终态值都自动被兜底覆盖。
ACTIVE_AI_TOOL_STATUSES = (
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_SYNC_QUEUED,
    AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
    AI_TOOL_STATUS_WAITING_BEFORE_FINISH,
    AI_TOOL_STATUS_DOWNLOADING,
)

DEFAULT_RECLAIM_INTERVAL_SECONDS = 3600
DEFAULT_RECLAIM_GRACE_SECONDS = 600


def get_reclaim_interval_seconds() -> int:
    """回收周期（秒），可经动态配置 runninghub.slot_reclaim_interval_seconds 覆盖。

    对账回收是兜底守护而非实时路径：各业务路径自身的即时释放才是主渠道，
    残留槽位晚至多一个周期被收即可，默认 1 小时足够（也把守护的常驻开销
    压到最低）。下限 60s 仅防误配出过小值。
    """
    return max(int(get_dynamic_config_value(
        "runninghub", "slot_reclaim_interval_seconds",
        default=DEFAULT_RECLAIM_INTERVAL_SECONDS,
    )), 60)


def get_reclaim_grace_seconds() -> int:
    """终态槽位回收宽限（秒），可经动态配置 runninghub.slot_reclaim_grace_seconds 覆盖。"""
    return max(int(get_dynamic_config_value(
        "runninghub", "slot_reclaim_grace_seconds",
        default=DEFAULT_RECLAIM_GRACE_SECONDS,
    )), 0)


def _find_reclaimable_slots() -> List[int]:
    """找出可回收的残留槽位（tasks 表主键 id 列表）。"""
    rows = execute_query(
        """
        SELECT s.task_id, s.id AS slot_id, t.id AS ai_id,
               t.status AS ai_status, t.completed_time
        FROM runninghub_slots s
        LEFT JOIN ai_tools t ON t.id = s.task_id
        WHERE s.source = %s AND s.status = 1
        """,
        (RunningHubSlot.SOURCE_TASK,),
        fetch_all=True,
    ) or []
    if not rows:
        return []

    from datetime import datetime
    grace_seconds = get_reclaim_grace_seconds()
    now = datetime.now()
    reclaimable: List[int] = []

    for row in rows:
        ai_status = row.get("ai_status")
        if ai_status is None:
            # ai_tools 记录已不存在（极端不一致）→ 槽位必然是残留
            logger.warning("[SlotReclaim] ai_tools missing for slot row, reclaim: %s", row)
            reclaimable.append(row["task_id"])
            continue

        if ai_status in ACTIVE_AI_TOOL_STATUSES:
            continue  # 任务活跃，槽位归其正常生命周期

        completed_time = row.get("completed_time")
        if completed_time is None:
            logger.warning(
                "[SlotReclaim] terminal task (status=%s) with NULL completed_time, "
                "skip and needs manual check: task_id=%s",
                ai_status, row["task_id"],
            )
            continue

        elapsed = (now - completed_time).total_seconds()
        if elapsed < grace_seconds:
            continue  # 终态刚落库，调度器可能仍在途提交，宽限期内不动

        reclaimable.append(row["task_id"])

    return reclaimable


def reclaim_stale_slots() -> int:
    """
    对账回收一轮残留槽位。

    Returns:
        本轮回收的槽位数量
    """
    try:
        reclaimable = _find_reclaimable_slots()
    except Exception as e:
        logger.error("[SlotReclaim] scan failed: %s", e)
        return 0

    reclaimed = 0
    for task_id in reclaimable:
        try:
            affected = RunningHubSlotsModel.release_slot(
                task_id, source=RunningHubSlot.SOURCE_TASK
            )
            if affected:
                reclaimed += 1
                logger.info(
                    "[SlotReclaim] reclaimed stale slot for task_id=%s (task terminal, slot orphaned)",
                    task_id,
                )
        except Exception as e:
            logger.error("[SlotReclaim] release failed for task_id=%s: %s", task_id, e)
    return reclaimed
