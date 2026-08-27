"""管理后台队列积压聚合（只读 COUNT）。

给 admin 首页看板用：各调度队列的待处理 / 处理中 / 停滞数量，以及
RunningHub 槽位占用。全部走索引友好的 WHERE status IN (...) COUNT，
单表失败不影响其它卡片。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from config.config_util import get_dynamic_config_value
from config.constant import (
    AI_TOOL_STATUS_DOWNLOADING,
    QueueBacklogConstants,
    ScriptSplitConstants,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_QUEUED,
    TASK_STATUS_SYNC_QUEUED,
    TASK_STATUS_WAITING_BEFORE_FINISH,
    TASK_STATUS_WAITING_PARAM_PREPARE,
    TASK_TYPE_GENERATE_AUDIO,
    TASK_TYPE_GENERATE_VIDEO,
)
from model.database import execute_query
from model.download_queue import (
    DQ_STATUS_PENDING,
    DQ_STATUS_PROCESSING,
    DQ_STATUS_SUCCESS,
)
from model.ai_tool_pipeline_steps import PipelineStepStatus
from model.async_tasks import AsyncTaskStatus
from model.grid_image_tasks import GridImageTaskStatus

logger = logging.getLogger(__name__)

_ALLOWED_TABLES = frozenset({
    "download_queue",
    "ai_tools",
    "tasks",
    "async_tasks",
    "grid_image_tasks",
    "script_split_task",
    "ai_tool_pipeline_steps",
    "runninghub_slots",
    "agent_tasks",
})

_LEVEL_RANK = {"unknown": 0, "ok": 1, "warn": 2, "danger": 3}

_SCRIPT_WORKING = (
    ScriptSplitConstants.STATUS_PLANNING,
    ScriptSplitConstants.STATUS_GENERATING,
    ScriptSplitConstants.STATUS_MERGING,
    ScriptSplitConstants.STATUS_VALIDATING,
    ScriptSplitConstants.STATUS_PUBLISHING,
    ScriptSplitConstants.STATUS_CANCELLING,
)

_TASK_OPEN_STATUSES = (
    TASK_STATUS_QUEUED,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SYNC_QUEUED,
    TASK_STATUS_WAITING_PARAM_PREPARE,
    TASK_STATUS_WAITING_BEFORE_FINISH,
)

_TASK_ACTIVE_STATUSES = (
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SYNC_QUEUED,
    TASK_STATUS_WAITING_PARAM_PREPARE,
    TASK_STATUS_WAITING_BEFORE_FINISH,
)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _int_config(*keys, default: int) -> int:
    try:
        value = int(get_dynamic_config_value(*keys, default=default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _stale_minutes() -> int:
    return _int_config(
        "download_queue_health", "stale_minutes",
        default=QueueBacklogConstants.STALE_MINUTES,
    )


def _zero_progress_minutes() -> int:
    return _int_config(
        "download_queue_health", "zero_progress_minutes",
        default=QueueBacklogConstants.ZERO_PROGRESS_MINUTES,
    )


def _classify(*, danger: bool = False, warn: bool = False) -> str:
    if danger:
        return "danger"
    if warn:
        return "warn"
    return "ok"


def _overall_level(levels: Iterable[str]) -> str:
    best = "ok"
    for level in levels:
        if _LEVEL_RANK.get(level, 0) > _LEVEL_RANK.get(best, 0):
            best = level
    return best


def _metric(key: str, value: int, alert: bool = False) -> Dict[str, Any]:
    return {"key": key, "value": int(value), "alert": bool(alert)}


def _card(
    qid: str,
    *,
    level: str,
    headline: Optional[int],
    headline_key: str,
    metrics: List[Dict[str, Any]],
    hint: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": qid,
        "level": level,
        "headline": headline,
        "headline_key": headline_key,
        "metrics": metrics,
        "hint": hint,
    }


def _error_card(qid: str) -> Dict[str, Any]:
    return _card(
        qid,
        level="unknown",
        headline=None,
        headline_key="unavailable",
        metrics=[],
        hint="unavailable",
    )


def _query_all(sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    return execute_query(sql, tuple(params), fetch_all=True) or []


def _query_one(sql: str, params: Sequence[Any] = ()) -> Dict[str, Any]:
    return execute_query(sql, tuple(params), fetch_one=True) or {}


def _count(sql: str, params: Sequence[Any] = ()) -> int:
    return _as_int(_query_one(sql, params).get("c"))


def _status_map(rows: Iterable[Dict[str, Any]]) -> Dict[Any, int]:
    out: Dict[Any, int] = {}
    for row in rows or []:
        out[row.get("s")] = _as_int(row.get("c"))
    return out


def _group_status(table: str, statuses: Sequence[Any], status_col: str = "status") -> Dict[Any, int]:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"unexpected table {table}")
    if not statuses:
        return {}
    placeholders = ",".join(["%s"] * len(statuses))
    sql = (
        f"SELECT {status_col} AS s, COUNT(*) AS c "
        f"FROM {table} WHERE {status_col} IN ({placeholders}) GROUP BY {status_col}"
    )
    return _status_map(_query_all(sql, statuses))


def _safe_card(qid: str, collector: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    try:
        card = collector()
        card["id"] = qid
        return card
    except Exception:
        logger.exception("queue backlog collect failed: %s", qid)
        return _error_card(qid)


def _collect_download_queue() -> Dict[str, Any]:
    stale_cutoff = datetime.now() - timedelta(minutes=_stale_minutes())
    progress_cutoff = datetime.now() - timedelta(minutes=_zero_progress_minutes())
    counts = _group_status(
        "download_queue", (DQ_STATUS_PENDING, DQ_STATUS_PROCESSING)
    )
    pending = counts.get(DQ_STATUS_PENDING, 0)
    processing = counts.get(DQ_STATUS_PROCESSING, 0)
    open_count = pending + processing
    stale = _count(
        "SELECT COUNT(*) AS c FROM download_queue "
        "WHERE status = %s AND create_at < %s",
        (DQ_STATUS_PROCESSING, stale_cutoff),
    )
    lease_expired = _count(
        "SELECT COUNT(*) AS c FROM download_queue "
        "WHERE status = %s AND lease_until IS NOT NULL AND lease_until < NOW()",
        (DQ_STATUS_PROCESSING,),
    )
    recent_success = _count(
        "SELECT COUNT(*) AS c FROM download_queue "
        "WHERE status = %s AND update_at >= %s",
        (DQ_STATUS_SUCCESS, progress_cutoff),
    )
    try:
        downloading = _count(
            "SELECT COUNT(*) AS c FROM ai_tools WHERE status = %s",
            (AI_TOOL_STATUS_DOWNLOADING,),
        )
    except Exception:
        logger.warning("queue backlog: ai_tools downloading count failed", exc_info=True)
        downloading = 0
    zero_progress = open_count > 0 and recent_success == 0
    danger = stale > 0 or zero_progress
    warn = (not danger) and (
        open_count >= QueueBacklogConstants.DOWNLOAD_WARN_OPEN or lease_expired > 0
    )
    hint = None
    if stale > 0:
        hint = "stale"
    elif zero_progress:
        hint = "zero_progress"
    elif lease_expired > 0:
        hint = "lease_expired"
    elif warn:
        hint = "backlog"
    return _card(
        "download_queue",
        level=_classify(danger=danger, warn=warn),
        headline=open_count,
        headline_key="open",
        metrics=[
            _metric("pending", pending),
            _metric("processing", processing, alert=processing > 0 and stale > 0),
            _metric("stale", stale, alert=stale > 0),
            _metric("lease_expired", lease_expired, alert=lease_expired > 0),
            _metric("recent_success", recent_success, alert=zero_progress),
            _metric("downloading", downloading),
        ],
        hint=hint,
    )


def _task_type_counts(
    rows: Iterable[Dict[str, Any]], task_type: str
) -> Dict[Any, int]:
    out: Dict[Any, int] = {}
    for row in rows or []:
        if row.get("task_type") != task_type:
            continue
        out[row.get("s")] = _as_int(row.get("c"))
    return out


def _collect_generate_tasks(qid: str, task_type: str, warn_open: int) -> Dict[str, Any]:
    stale_cutoff = datetime.now() - timedelta(minutes=_stale_minutes())
    overdue_cutoff = datetime.now() - timedelta(
        seconds=QueueBacklogConstants.OVERDUE_GRACE_SECONDS
    )
    placeholders = ",".join(["%s"] * len(_TASK_OPEN_STATUSES))
    grouped = _query_all(
        "SELECT task_type, status AS s, COUNT(*) AS c FROM tasks "
        f"WHERE status IN ({placeholders}) GROUP BY task_type, status",
        _TASK_OPEN_STATUSES,
    )
    counts = _task_type_counts(grouped, task_type)
    queued = counts.get(TASK_STATUS_QUEUED, 0)
    processing = counts.get(TASK_STATUS_PROCESSING, 0)
    sync_queued = counts.get(TASK_STATUS_SYNC_QUEUED, 0)
    waiting_param = counts.get(TASK_STATUS_WAITING_PARAM_PREPARE, 0)
    waiting_finish = counts.get(TASK_STATUS_WAITING_BEFORE_FINISH, 0)
    open_count = queued + processing + sync_queued + waiting_param + waiting_finish

    stale_placeholders = ",".join(["%s"] * len(_TASK_ACTIVE_STATUSES))
    stale_rows = _query_all(
        "SELECT task_type, COUNT(*) AS c FROM tasks "
        f"WHERE status IN ({stale_placeholders}) AND updated_at < %s "
        "GROUP BY task_type",
        (*_TASK_ACTIVE_STATUSES, stale_cutoff),
    )
    stale = 0
    for row in stale_rows:
        if row.get("task_type") == task_type:
            stale = _as_int(row.get("c"))
            break

    overdue_rows = _query_all(
        "SELECT task_type, COUNT(*) AS c FROM tasks "
        "WHERE status = %s AND next_trigger < %s GROUP BY task_type",
        (TASK_STATUS_QUEUED, overdue_cutoff),
    )
    overdue = 0
    for row in overdue_rows:
        if row.get("task_type") == task_type:
            overdue = _as_int(row.get("c"))
            break

    danger = stale > 0
    warn = (not danger) and (open_count >= warn_open or overdue > 0)
    hint = None
    if stale > 0:
        hint = "stale"
    elif overdue > 0:
        hint = "overdue"
    elif warn:
        hint = "backlog"
    return _card(
        qid,
        level=_classify(danger=danger, warn=warn),
        headline=open_count,
        headline_key="open",
        metrics=[
            _metric("queued", queued, alert=overdue > 0),
            _metric("processing", processing, alert=stale > 0),
            _metric("sync_queued", sync_queued),
            _metric("waiting_param", waiting_param),
            _metric("waiting_finish", waiting_finish),
            _metric("stale", stale, alert=stale > 0),
            _metric("overdue", overdue, alert=overdue > 0),
        ],
        hint=hint,
    )


def _collect_generate_video() -> Dict[str, Any]:
    return _collect_generate_tasks(
        "generate_video", TASK_TYPE_GENERATE_VIDEO, QueueBacklogConstants.VIDEO_WARN_OPEN
    )


def _collect_generate_audio() -> Dict[str, Any]:
    return _collect_generate_tasks(
        "generate_audio", TASK_TYPE_GENERATE_AUDIO, QueueBacklogConstants.AUDIO_WARN_OPEN
    )


def _collect_async_tasks() -> Dict[str, Any]:
    stale_cutoff = datetime.now() - timedelta(minutes=_stale_minutes())
    counts = _group_status(
        "async_tasks", (AsyncTaskStatus.QUEUED, AsyncTaskStatus.PROCESSING)
    )
    queued = counts.get(AsyncTaskStatus.QUEUED, 0)
    processing = counts.get(AsyncTaskStatus.PROCESSING, 0)
    open_count = queued + processing
    stale = _count(
        "SELECT COUNT(*) AS c FROM async_tasks "
        "WHERE status IN (%s, %s) AND updated_at < %s",
        (AsyncTaskStatus.QUEUED, AsyncTaskStatus.PROCESSING, stale_cutoff),
    )
    danger = stale > 0
    warn = (not danger) and open_count >= QueueBacklogConstants.ASYNC_WARN_OPEN
    hint = "stale" if danger else ("backlog" if warn else None)
    return _card(
        "async_tasks",
        level=_classify(danger=danger, warn=warn),
        headline=open_count,
        headline_key="open",
        metrics=[
            _metric("queued", queued),
            _metric("processing", processing, alert=stale > 0),
            _metric("stale", stale, alert=stale > 0),
        ],
        hint=hint,
    )


def _collect_grid_image() -> Dict[str, Any]:
    stale_cutoff = datetime.now() - timedelta(minutes=_stale_minutes())
    counts = _group_status(
        "grid_image_tasks",
        (GridImageTaskStatus.QUEUED, GridImageTaskStatus.PROCESSING),
    )
    queued = counts.get(GridImageTaskStatus.QUEUED, 0)
    processing = counts.get(GridImageTaskStatus.PROCESSING, 0)
    open_count = queued + processing
    stale = _count(
        "SELECT COUNT(*) AS c FROM grid_image_tasks "
        "WHERE status IN (%s, %s) AND updated_at < %s",
        (GridImageTaskStatus.QUEUED, GridImageTaskStatus.PROCESSING, stale_cutoff),
    )
    danger = stale > 0
    warn = (not danger) and open_count >= QueueBacklogConstants.GRID_WARN_OPEN
    hint = "stale" if danger else ("backlog" if warn else None)
    return _card(
        "grid_image",
        level=_classify(danger=danger, warn=warn),
        headline=open_count,
        headline_key="open",
        metrics=[
            _metric("queued", queued),
            _metric("processing", processing, alert=stale > 0),
            _metric("stale", stale, alert=stale > 0),
        ],
        hint=hint,
    )


def _collect_script_split() -> Dict[str, Any]:
    counts = _group_status("script_split_task", ScriptSplitConstants.ACTIVE_STATUSES)
    queued = counts.get(ScriptSplitConstants.STATUS_QUEUED, 0)
    working = sum(counts.get(status, 0) for status in _SCRIPT_WORKING)
    paused = counts.get(ScriptSplitConstants.STATUS_PAUSED, 0)
    waiting_auth = counts.get(ScriptSplitConstants.STATUS_WAITING_AUTH, 0)
    open_count = queued + working
    placeholders = ",".join(["%s"] * len(_SCRIPT_WORKING))
    stale = _count(
        "SELECT COUNT(*) AS c FROM script_split_task "
        f"WHERE status IN ({placeholders}) "
        "AND lease_until IS NOT NULL AND lease_until < NOW()",
        _SCRIPT_WORKING,
    )
    danger = stale > 0
    warn = (not danger) and open_count >= QueueBacklogConstants.SCRIPT_SPLIT_WARN_OPEN
    hint = None
    if stale > 0:
        hint = "stale"
    elif warn:
        hint = "backlog"
    return _card(
        "script_split",
        level=_classify(danger=danger, warn=warn),
        headline=open_count,
        headline_key="open",
        metrics=[
            _metric("queued", queued),
            _metric("working", working, alert=stale > 0),
            _metric("paused", paused),
            _metric("waiting_auth", waiting_auth),
            _metric("stale", stale, alert=stale > 0),
        ],
        hint=hint,
    )


def _collect_pipeline_steps() -> Dict[str, Any]:
    stale_cutoff = datetime.now() - timedelta(minutes=_stale_minutes())
    counts = _group_status(
        "ai_tool_pipeline_steps",
        (PipelineStepStatus.PENDING, PipelineStepStatus.PROCESSING),
    )
    pending = counts.get(PipelineStepStatus.PENDING, 0)
    processing = counts.get(PipelineStepStatus.PROCESSING, 0)
    open_count = pending + processing
    stale = _count(
        "SELECT COUNT(*) AS c FROM ai_tool_pipeline_steps "
        "WHERE status = %s AND updated_at < %s",
        (PipelineStepStatus.PROCESSING, stale_cutoff),
    )
    danger = stale > 0
    warn = (not danger) and open_count >= QueueBacklogConstants.PIPELINE_WARN_OPEN
    hint = "stale" if danger else ("backlog" if warn else None)
    return _card(
        "pipeline_steps",
        level=_classify(danger=danger, warn=warn),
        headline=open_count,
        headline_key="open",
        metrics=[
            _metric("pending", pending),
            _metric("processing", processing, alert=stale > 0),
            _metric("stale", stale, alert=stale > 0),
        ],
        hint=hint,
    )


def _collect_runninghub_slots() -> Dict[str, Any]:
    used = _count(
        "SELECT COUNT(*) AS c FROM runninghub_slots WHERE status = %s",
        (1,),
    )
    try:
        max_slots = int(
            get_dynamic_config_value("runninghub", "max_concurrent_slots", default=3) or 3
        )
    except (TypeError, ValueError):
        max_slots = 3
    if max_slots < 0:
        max_slots = 0
    free = max(max_slots - used, 0)
    ratio = (used / max_slots) if max_slots > 0 else 0.0
    danger = max_slots > 0 and used >= max_slots
    warn = (not danger) and max_slots > 0 and ratio >= QueueBacklogConstants.RUNNINGHUB_WARN_RATIO
    hint = "full" if danger else ("backlog" if warn else None)
    return _card(
        "runninghub_slots",
        level=_classify(danger=danger, warn=warn),
        headline=used,
        headline_key="slots_used",
        metrics=[
            _metric("used", used, alert=danger),
            _metric("max", max_slots),
            _metric("free", free, alert=danger),
        ],
        hint=hint,
    )


def _collect_agent_tasks() -> Dict[str, Any]:
    stale_cutoff = datetime.now() - timedelta(minutes=_stale_minutes())
    counts = _group_status(
        "agent_tasks", ("pending", "running", "waiting_human")
    )
    pending = counts.get("pending", 0)
    running = counts.get("running", 0)
    waiting_human = counts.get("waiting_human", 0)
    open_count = pending + running
    stale = _count(
        "SELECT COUNT(*) AS c FROM agent_tasks "
        "WHERE status = %s AND COALESCE(started_at, created_at) < %s",
        ("running", stale_cutoff),
    )
    danger = stale > 0
    warn = (not danger) and open_count >= QueueBacklogConstants.AGENT_WARN_OPEN
    hint = "stale" if danger else ("backlog" if warn else None)
    return _card(
        "agent_tasks",
        level=_classify(danger=danger, warn=warn),
        headline=open_count,
        headline_key="open",
        metrics=[
            _metric("pending", pending),
            _metric("running", running, alert=stale > 0),
            _metric("waiting_human", waiting_human),
            _metric("stale", stale, alert=stale > 0),
        ],
        hint=hint,
    )


_COLLECTORS = (
    ("download_queue", _collect_download_queue),
    ("generate_video", _collect_generate_video),
    ("generate_audio", _collect_generate_audio),
    ("async_tasks", _collect_async_tasks),
    ("grid_image", _collect_grid_image),
    ("script_split", _collect_script_split),
    ("pipeline_steps", _collect_pipeline_steps),
    ("runninghub_slots", _collect_runninghub_slots),
    ("agent_tasks", _collect_agent_tasks),
)


def collect_queue_backlog() -> Dict[str, Any]:
    """同步只读聚合。由 API 经 asyncio.to_thread 调用，禁止在事件循环里直接跑。"""
    queues = [_safe_card(qid, collector) for qid, collector in _COLLECTORS]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stale_minutes": _stale_minutes(),
        "overall": _overall_level(q.get("level") for q in queues),
        "queues": queues,
    }
