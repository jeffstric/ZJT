"""download_queue 健康检查 job。

覆盖「worker 活着但不干活」类故障（2026-08-21 UnboundLocalError 静默瘫痪）：
队列有 pending/processing，但长时间没有成功行。

已知盲区：本 job 与 download_queue_worker 同属 scheduler，scheduler 整体死亡时
两者都不跑。本次事故类型（worker 进程活着、功能坏掉）能覆盖。

全部只读 SQL，不改数据。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from config.config_util import get_dynamic_config_value
from model.database import execute_query
from model.download_queue import (
    DQ_STATUS_PENDING,
    DQ_STATUS_PROCESSING,
    DQ_STATUS_SUCCESS,
)
from utils.sentry_util import AlertLevel, SentryUtil

logger = logging.getLogger(__name__)

_DEFAULT_STALE_MINUTES = 30
_DEFAULT_ZERO_PROGRESS_MINUTES = 10
_DEFAULT_ALERT_INTERVAL_MINUTES = 30

_last_alert_at = 0.0


def _int_config(*keys, default: int) -> int:
    try:
        value = int(get_dynamic_config_value(*keys, default=default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _maybe_alert(message: str, context: dict) -> None:
    """限频去重：默认 30 分钟一条 DOWNLOAD_QUEUE_STALLED。"""
    global _last_alert_at
    interval_minutes = _int_config(
        "download_queue_health", "alert_interval_minutes",
        default=_DEFAULT_ALERT_INTERVAL_MINUTES,
    )
    now = time.monotonic()
    if _last_alert_at and (now - _last_alert_at) < interval_minutes * 60:
        logger.warning("[DownloadQueueHealth] suppressed duplicate alert: %s", message)
        return
    _last_alert_at = now
    try:
        SentryUtil.send_alert(
            "DOWNLOAD_QUEUE_STALLED",
            message,
            level=AlertLevel.ERROR,
            context=context,
        )
    except Exception:
        logger.exception("[DownloadQueueHealth] send_alert failed")


def check_download_queue_health() -> None:
    """积压停滞 + 零进展。开关关闭则直接返回。"""
    try:
        enabled = get_dynamic_config_value(
            "download_queue_health", "enabled", default=True
        )
        if not enabled:
            return

        stale_minutes = _int_config(
            "download_queue_health", "stale_minutes", default=_DEFAULT_STALE_MINUTES
        )
        zero_progress_minutes = _int_config(
            "download_queue_health", "zero_progress_minutes",
            default=_DEFAULT_ZERO_PROGRESS_MINUTES,
        )
        now = datetime.now()
        stale_cutoff = now - timedelta(minutes=stale_minutes)
        progress_cutoff = now - timedelta(minutes=zero_progress_minutes)

        stale_row = execute_query(
            "SELECT COUNT(*) AS c FROM download_queue "
            "WHERE status = %s AND create_at < %s",
            (DQ_STATUS_PROCESSING, stale_cutoff),
            fetch_one=True,
        ) or {}
        stale_count = int(stale_row.get("c") or 0)

        open_row = execute_query(
            "SELECT COUNT(*) AS c FROM download_queue WHERE status IN (%s, %s)",
            (DQ_STATUS_PENDING, DQ_STATUS_PROCESSING),
            fetch_one=True,
        ) or {}
        open_count = int(open_row.get("c") or 0)

        success_row = execute_query(
            "SELECT COUNT(*) AS c FROM download_queue "
            "WHERE status = %s AND update_at >= %s",
            (DQ_STATUS_SUCCESS, progress_cutoff),
            fetch_one=True,
        ) or {}
        recent_success = int(success_row.get("c") or 0)

        if stale_count > 0:
            _maybe_alert(
                f"download_queue 积压停滞: {stale_count} 行 status=1 且 create_at 超过 "
                f"{stale_minutes} 分钟",
                {
                    "check": "stale_processing",
                    "stale_count": stale_count,
                    "stale_minutes": stale_minutes,
                },
            )
            return

        if open_count > 0 and recent_success == 0:
            _maybe_alert(
                f"download_queue 零进展: {open_count} 行 pending/processing，"
                f"最近 {zero_progress_minutes} 分钟成功数为 0",
                {
                    "check": "zero_progress",
                    "open_count": open_count,
                    "zero_progress_minutes": zero_progress_minutes,
                    "recent_success": recent_success,
                },
            )
    except Exception:
        logger.exception("[DownloadQueueHealth] health check failed")
