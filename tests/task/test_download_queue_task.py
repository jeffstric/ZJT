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


def _fake_license_denied() -> Exception:
    """构造模拟"许可证校验失败"的异常（由门面 stub provider 判定为许可证类）。"""
    cls = type("SimulatedLicenseError", (Exception,), {})
    return cls("商业许可证租约已经过期")


class _LicenseErrorClassifyingProvider:
    """模拟商业版续租实现的错误分类：模拟标记类视为许可证类非瞬态错误。"""

    available = True

    def rebootstrap(self) -> None:
        pass

    def is_non_transient_error(self, exc: BaseException) -> bool:
        return exc.__class__.__name__ == "SimulatedLicenseError"


class _LoggerStub:
    """捕获 error/warning/info 调用，避免污染测试输出并便于断言。"""

    def __init__(self):
        self.errors = []

    def error(self, msg, *args, **kwargs):
        self.errors.append(msg)

    def warning(self, msg, *args, **kwargs):
        pass

    def info(self, msg, *args, **kwargs):
        pass

    def exception(self, msg, *args, **kwargs):
        self.errors.append(msg)


def test_process_one_license_denied_reschedules_with_long_backoff(monkeypatch):
    """下载成功后写库阶段被商业许可证拦截：必须长退避置回 pending。

    回归 2026-09-15 事故：旧实现只在租约过期后回收重试，每 20 分钟循环失败
    并重复下载；且不计 try_count（不是下载本身的过错）。
    """
    from task import license_rebootstrap_task as facade

    facade.register_provider(_LicenseErrorClassifyingProvider())
    captured = _patch_common(monkeypatch, download_result="/upload/cache/ok.mp4")

    async def denying_postprocess(*, ai_tool_id, result_url, media_type):
        raise _fake_license_denied()

    logger_stub = _LoggerStub()
    monkeypatch.setattr(download_worker, "maybe_trim_generated_face_grid_prefix", denying_postprocess)
    monkeypatch.setattr(download_worker, "logger", logger_stub)

    try:
        asyncio.run(download_worker._process_one(_row(try_count=1)))
    finally:
        facade.reset_provider()

    assert captured["success"] == []
    assert captured["updates"] == []
    assert len(captured["reschedule"]) == 1
    row_id, try_count, err = captured["reschedule"][0]
    assert row_id == 11
    assert try_count == 1  # try_count 不变：不消耗下载重试次数
    assert "license denied" in err
    # 走 RETRY_SCHEDULED 事件留痕，且没有落到旧的 success-but-update-failed 路径
    events = [event for event, _kwargs in captured["logs"]]
    assert download_worker.AIToolsLogEvent.RETRY_SCHEDULED in events
    assert not any("success-but-update-failed" in msg for msg in logger_stub.errors)


def test_process_one_success_path_other_error_keeps_legacy_behavior(monkeypatch):
    """非许可证异常维持旧行为：仅记录错误日志，留待租约回收重试。"""
    captured = _patch_common(monkeypatch, download_result="/upload/cache/ok.mp4")

    async def boom_postprocess(*, ai_tool_id, result_url, media_type):
        raise RuntimeError("db connection lost")

    logger_stub = _LoggerStub()
    monkeypatch.setattr(download_worker, "maybe_trim_generated_face_grid_prefix", boom_postprocess)
    monkeypatch.setattr(download_worker, "logger", logger_stub)

    asyncio.run(download_worker._process_one(_row()))

    assert captured["success"] == []
    assert captured["updates"] == []
    assert captured["reschedule"] == []
    assert any("success-but-update-failed" in msg for msg in logger_stub.errors)


def test_process_one_license_error_not_classified_without_enterprise_provider(monkeypatch):
    """未注册商业版实现（社区版）时，同名异常不应被误判为许可证类错误。"""
    from task import license_rebootstrap_task as facade

    assert facade.is_available() is False
    captured = _patch_common(monkeypatch, download_result="/upload/cache/ok.mp4")

    async def denying_postprocess(*, ai_tool_id, result_url, media_type):
        raise _fake_license_denied()

    logger_stub = _LoggerStub()
    monkeypatch.setattr(download_worker, "maybe_trim_generated_face_grid_prefix", denying_postprocess)
    monkeypatch.setattr(download_worker, "logger", logger_stub)

    asyncio.run(download_worker._process_one(_row()))

    # 社区门面判定为非瞬态错误=False → 走旧路径（仅记录，留待租约回收）
    assert captured["reschedule"] == []
    assert any("success-but-update-failed" in msg for msg in logger_stub.errors)
