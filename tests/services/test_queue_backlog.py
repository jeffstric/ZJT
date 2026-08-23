"""队列积压聚合：按 SQL 形态 mock execute_query，不连真实 DB。"""
from datetime import datetime

import pytest

from config.constant import (
    QueueBacklogConstants,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_QUEUED,
    TASK_TYPE_GENERATE_AUDIO,
    TASK_TYPE_GENERATE_VIDEO,
)
from model.download_queue import DQ_STATUS_PENDING, DQ_STATUS_PROCESSING
from services import queue_backlog as qb


def _norm(sql: str) -> str:
    return " ".join((sql or "").split()).lower()


def _config_side_effect(*keys, default=None):
    mapping = {
        ("download_queue_health", "stale_minutes"): 30,
        ("download_queue_health", "zero_progress_minutes"): 10,
        ("runninghub", "max_concurrent_slots"): 3,
    }
    return mapping.get(keys, default)


def _install_query(monkeypatch, handler):
    monkeypatch.setattr(qb, "execute_query", handler)
    monkeypatch.setattr(qb, "get_dynamic_config_value", _config_side_effect)


def _by_id(payload, qid):
    for card in payload["queues"]:
        if card["id"] == qid:
            return card
    raise AssertionError(f"missing queue {qid}")


def _metric(card, key):
    for item in card["metrics"]:
        if item["key"] == key:
            return item["value"]
    raise AssertionError(f"missing metric {key}")


def test_all_empty_is_ok(monkeypatch):
    def handler(sql, params=None, fetch_one=False, fetch_all=False):
        if fetch_all:
            return []
        return {"c": 0}

    _install_query(monkeypatch, handler)
    payload = qb.collect_queue_backlog()
    assert payload["overall"] == "ok"
    assert payload["stale_minutes"] == 30
    assert datetime.strptime(payload["generated_at"], "%Y-%m-%d %H:%M:%S")
    ids = [q["id"] for q in payload["queues"]]
    assert ids == [
        "download_queue",
        "generate_video",
        "generate_audio",
        "async_tasks",
        "grid_image",
        "script_split",
        "pipeline_steps",
        "runninghub_slots",
        "agent_tasks",
    ]
    for card in payload["queues"]:
        assert card["level"] == "ok"
        assert card["headline"] in (0,)


def test_download_queue_stale_is_danger(monkeypatch):
    def handler(sql, params=None, fetch_one=False, fetch_all=False):
        s = _norm(sql)
        if "from download_queue" in s and "group by" in s:
            return [
                {"s": DQ_STATUS_PENDING, "c": 1},
                {"s": DQ_STATUS_PROCESSING, "c": 2},
            ]
        if "from download_queue" in s and "create_at" in s:
            return {"c": 2}
        if fetch_all:
            return []
        return {"c": 0}

    _install_query(monkeypatch, handler)
    card = _by_id(qb.collect_queue_backlog(), "download_queue")
    assert card["level"] == "danger"
    assert card["hint"] == "stale"
    assert card["headline"] == 3
    assert _metric(card, "stale") == 2


def test_download_queue_zero_progress_is_danger(monkeypatch):
    def handler(sql, params=None, fetch_one=False, fetch_all=False):
        s = _norm(sql)
        if "from download_queue" in s and "group by" in s:
            return [{"s": DQ_STATUS_PENDING, "c": 5}]
        if "from download_queue" in s and "update_at" in s:
            return {"c": 0}
        if fetch_all:
            return []
        return {"c": 0}

    _install_query(monkeypatch, handler)
    payload = qb.collect_queue_backlog()
    card = _by_id(payload, "download_queue")
    assert card["level"] == "danger"
    assert card["hint"] == "zero_progress"
    assert payload["overall"] == "danger"


def test_download_queue_open_warn(monkeypatch):
    def handler(sql, params=None, fetch_one=False, fetch_all=False):
        s = _norm(sql)
        if "from download_queue" in s and "group by" in s:
            return [{"s": DQ_STATUS_PENDING, "c": QueueBacklogConstants.DOWNLOAD_WARN_OPEN}]
        if "from download_queue" in s and "update_at" in s:
            return {"c": 4}
        if fetch_all:
            return []
        return {"c": 0}

    _install_query(monkeypatch, handler)
    card = _by_id(qb.collect_queue_backlog(), "download_queue")
    assert card["level"] == "warn"
    assert card["hint"] == "backlog"


def test_generate_video_stale_and_audio_ok(monkeypatch):
    def handler(sql, params=None, fetch_one=False, fetch_all=False):
        s = _norm(sql)
        if "from tasks" in s and "group by task_type, status" in s:
            return [
                {
                    "task_type": TASK_TYPE_GENERATE_VIDEO,
                    "s": TASK_STATUS_PROCESSING,
                    "c": 3,
                },
                {
                    "task_type": TASK_TYPE_GENERATE_AUDIO,
                    "s": TASK_STATUS_QUEUED,
                    "c": 1,
                },
            ]
        if "from tasks" in s and "updated_at" in s:
            return [{"task_type": TASK_TYPE_GENERATE_VIDEO, "c": 3}]
        if fetch_all:
            return []
        return {"c": 0}

    _install_query(monkeypatch, handler)
    payload = qb.collect_queue_backlog()
    video = _by_id(payload, "generate_video")
    audio = _by_id(payload, "generate_audio")
    assert video["level"] == "danger"
    assert video["hint"] == "stale"
    assert video["headline"] == 3
    assert audio["level"] == "ok"
    assert audio["headline"] == 1
    assert payload["overall"] == "danger"


def test_runninghub_slots_full_is_danger(monkeypatch):
    def handler(sql, params=None, fetch_one=False, fetch_all=False):
        s = _norm(sql)
        if "from runninghub_slots" in s:
            return {"c": 3}
        if fetch_all:
            return []
        return {"c": 0}

    _install_query(monkeypatch, handler)
    payload = qb.collect_queue_backlog()
    card = _by_id(payload, "runninghub_slots")
    assert card["level"] == "danger"
    assert card["hint"] == "full"
    assert card["headline"] == 3
    assert _metric(card, "max") == 3
    assert _metric(card, "free") == 0


def test_single_table_failure_is_isolated(monkeypatch):
    def handler(sql, params=None, fetch_one=False, fetch_all=False):
        s = _norm(sql)
        if "from download_queue" in s:
            raise RuntimeError("table missing")
        if fetch_all:
            return []
        return {"c": 0}

    _install_query(monkeypatch, handler)
    payload = qb.collect_queue_backlog()
    failed = _by_id(payload, "download_queue")
    assert failed["level"] == "unknown"
    assert failed["hint"] == "unavailable"
    assert failed["headline"] is None
    video = _by_id(payload, "generate_video")
    assert video["level"] == "ok"
    assert payload["overall"] == "ok"


def test_script_split_stale_lease(monkeypatch):
    def handler(sql, params=None, fetch_one=False, fetch_all=False):
        s = _norm(sql)
        if "from script_split_task" in s and "group by" in s:
            return [{"s": "generating", "c": 2}, {"s": "queued", "c": 1}]
        if "from script_split_task" in s and "lease_until" in s:
            return {"c": 1}
        if fetch_all:
            return []
        return {"c": 0}

    _install_query(monkeypatch, handler)
    card = _by_id(qb.collect_queue_backlog(), "script_split")
    assert card["headline"] == 3
    assert card["level"] == "danger"
    assert card["hint"] == "stale"
    assert _metric(card, "working") == 2
    assert _metric(card, "queued") == 1
