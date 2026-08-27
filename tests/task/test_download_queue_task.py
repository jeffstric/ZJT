"""download_queue_task 路径与 gather 异常留痕（不连 DB）。"""
import asyncio
from types import SimpleNamespace

from task import download_queue_task as download_worker


def _row(**overrides):
    base = {
        "id": 11,
        "ai_tool_id": 501,
        "project_id": "p-501",
        "remote_url": "https://example.test/v.mp4",
        "media_type": "video",
        "try_count": 0,
        "max_try": 3,
    }
    base.update(overrides)
    return base


def _patch_common(monkeypatch, *, download_result=None, download_error=None):
    captured = {
        "success": [],
        "reschedule": [],
        "failed": [],
        "updates": [],
        "logs": [],
    }

    class CacheManager:
        async def download_and_cache(self, *args, **kwargs):
            if download_error is not None:
                raise download_error
            return download_result

    async def fake_postprocess(*, ai_tool_id, result_url, media_type):
        return SimpleNamespace(result_url=result_url)

    monkeypatch.setattr(download_worker, "get_cache_manager", lambda: CacheManager())
    monkeypatch.setattr(
        download_worker, "maybe_trim_generated_face_grid_prefix", fake_postprocess
    )
    monkeypatch.setattr(
        download_worker.AIToolsModel,
        "update_by_project_id_with_cdn_sync",
        lambda **kwargs: captured["updates"].append(kwargs),
    )
    monkeypatch.setattr(
        download_worker.DownloadQueueModel,
        "mark_success",
        lambda row_id, result_url: captured["success"].append((row_id, result_url)),
    )
    monkeypatch.setattr(
        download_worker.DownloadQueueModel,
        "reschedule",
        lambda row_id, try_count, next_trigger, err: captured["reschedule"].append(
            (row_id, try_count, err)
        ),
    )
    monkeypatch.setattr(
        download_worker.DownloadQueueModel,
        "mark_failed",
        lambda row_id, err: captured["failed"].append((row_id, err)),
    )
    monkeypatch.setattr(
        download_worker,
        "_log",
        lambda task_id, event, **kwargs: captured["logs"].append((event, kwargs)),
    )
    from model.implementation_attempts import ImplementationAttemptModel
    import utils.computing_power as computing_power

    monkeypatch.setattr(
        ImplementationAttemptModel, "mark_active_attempt_completed", lambda *_: None
    )
    monkeypatch.setattr(computing_power, "settle_success_diff_for_task", lambda *_: 0)
    return captured


def test_process_one_success_marks_and_logs(monkeypatch):
    captured = _patch_common(monkeypatch, download_result="/upload/cache/ok.mp4")
    asyncio.run(download_worker._process_one(_row()))
    assert captured["success"] == [(11, "/upload/cache/ok.mp4")]
    assert captured["updates"][0]["result_url"] == "/upload/cache/ok.mp4"
    assert len(captured["logs"]) == 2
    assert captured["reschedule"] == []
    assert captured["failed"] == []


def test_process_one_failure_reschedules(monkeypatch):
    captured = _patch_common(monkeypatch, download_result=None)
    asyncio.run(download_worker._process_one(_row(try_count=0, max_try=3)))
    assert captured["success"] == []
    assert len(captured["reschedule"]) == 1
    assert captured["reschedule"][0][0] == 11
    assert captured["failed"] == []


def test_process_one_max_try_fallback_completed(monkeypatch):
    captured = _patch_common(monkeypatch, download_result=None)
    asyncio.run(download_worker._process_one(_row(try_count=2, max_try=3)))
    assert captured["failed"]
    assert captured["updates"][0]["result_url"] == "https://example.test/v.mp4"
    assert captured["reschedule"] == []


def test_process_one_download_exception_is_recorded(monkeypatch):
    captured = _patch_common(
        monkeypatch, download_error=RuntimeError("disk full")
    )
    asyncio.run(download_worker._process_one(_row()))
    assert captured["reschedule"]
    assert "RuntimeError" in captured["reschedule"][0][2]
    assert captured["success"] == []


def test_process_download_queue_records_gather_exceptions(monkeypatch):
    claimed = {"n": 0}

    async def boom(_row):
        raise RuntimeError("silent-unbound")

    def claim_pending(**_kwargs):
        claimed["n"] += 1
        if claimed["n"] == 1:
            return [_row()]
        return []

    errors = []
    captures = []

    monkeypatch.setattr(download_worker, "_process_one", boom)
    monkeypatch.setattr(
        download_worker.DownloadQueueModel, "claim_pending", claim_pending
    )
    monkeypatch.setattr(download_worker, "DOWNLOAD_PER_ATTEMPT_TIMEOUT", 1)
    monkeypatch.setattr(download_worker, "DOWNLOAD_COMPLETION_MARGIN_SECONDS", 0)
    monkeypatch.setattr(download_worker, "DOWNLOAD_MAX_BATCHES_PER_TICK", 1)
    monkeypatch.setattr(
        download_worker,
        "GeneratedVideoFaceGridTrimConstants",
        SimpleNamespace(MAX_PROCESSING_SECONDS=0),
    )
    monkeypatch.setattr(
        download_worker.logger,
        "error",
        lambda msg, *args, **kwargs: errors.append((msg, args, kwargs)),
    )
    monkeypatch.setattr(
        download_worker.SentryUtil,
        "capture_exception",
        lambda exc: captures.append(exc),
    )

    asyncio.run(download_worker.process_download_queue())

    assert captures and isinstance(captures[0], RuntimeError)
    assert any("gather exception" in str(msg) for msg, _args, _kw in errors)
