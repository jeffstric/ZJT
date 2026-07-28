import asyncio
from types import SimpleNamespace

import pytest

from config import constant
from services import generated_video_face_grid_service as postprocess_service
from task import download_queue_task as download_worker
from task import sync_task_executor
from task import visual_task


def _result_url_from_update(calls):
    assert len(calls) == 1
    return calls[0]["result_url"]


def _patch_attempt_completion(monkeypatch):
    from model.implementation_attempts import ImplementationAttemptModel

    monkeypatch.setattr(ImplementationAttemptModel, "mark_active_attempt_completed", lambda *_: None)


def test_download_worker_persists_postprocessed_url_everywhere(monkeypatch):
    """遗漏后处理返回值时，下载成功路径会把未裁剪 URL 写入所有终态。"""
    captured_updates = []
    captured_queue_success = []
    captured_logs = []
    postprocess_calls = []

    class CacheManager:
        async def download_and_cache(self, remote_url, ai_tool_id, media_type, max_retries):
            assert (remote_url, ai_tool_id, media_type, max_retries) == (
                "https://example.test/generated.mp4",
                701,
                "video",
                1,
            )
            return "/upload/cache/original.mp4"

    async def fake_postprocess(*, ai_tool_id, result_url, media_type):
        postprocess_calls.append((ai_tool_id, result_url, media_type))
        return SimpleNamespace(result_url="/upload/cache/trimmed.mp4")

    monkeypatch.setattr(download_worker, "get_cache_manager", lambda: CacheManager())
    monkeypatch.setattr(
        download_worker,
        "maybe_trim_generated_face_grid_prefix",
        fake_postprocess,
        raising=False,
    )
    monkeypatch.setattr(
        download_worker.AIToolsModel,
        "update_by_project_id_with_cdn_sync",
        lambda **kwargs: captured_updates.append(kwargs),
    )
    monkeypatch.setattr(
        download_worker.DownloadQueueModel,
        "mark_success",
        lambda row_id, result_url: captured_queue_success.append((row_id, result_url)),
    )
    monkeypatch.setattr(download_worker, "_log", lambda task_id, event, **kwargs: captured_logs.append(kwargs))
    _patch_attempt_completion(monkeypatch)

    asyncio.run(
        download_worker._process_one(
            {
                "id": 91,
                "ai_tool_id": 701,
                "project_id": "project-701",
                "remote_url": "https://example.test/generated.mp4",
                "media_type": "video",
                "try_count": 0,
                "max_try": 3,
            }
        )
    )

    assert postprocess_calls == [(701, "/upload/cache/original.mp4", "video")]
    assert captured_updates[0]["result_url"] == "/upload/cache/trimmed.mp4"
    assert captured_queue_success == [(91, "/upload/cache/trimmed.mp4")]
    assert captured_logs[0]["detail"]["final_url"] == "/upload/cache/trimmed.mp4"
    assert captured_logs[1]["detail"]["result_url"] == "/upload/cache/trimmed.mp4"


def test_download_worker_propagates_postprocess_cancellation_before_terminal_writes(monkeypatch):
    """吞掉服务取消会把正在关闭的 worker 错误推进到 COMPLETED。"""
    terminal_updates = []

    class CacheManager:
        async def download_and_cache(self, *_args, **_kwargs):
            return "/upload/cache/original.mp4"

    async def cancelled_postprocess(**_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(download_worker, "get_cache_manager", lambda: CacheManager())
    monkeypatch.setattr(
        download_worker,
        "maybe_trim_generated_face_grid_prefix",
        cancelled_postprocess,
    )
    monkeypatch.setattr(
        download_worker.AIToolsModel,
        "update_by_project_id_with_cdn_sync",
        lambda **kwargs: terminal_updates.append(kwargs),
    )
    monkeypatch.setattr(
        download_worker.DownloadQueueModel,
        "mark_success",
        lambda *_: pytest.fail("取消后不得写队列成功终态"),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            download_worker._process_one(
                {
                    "id": 92,
                    "ai_tool_id": 702,
                    "project_id": "project-702",
                    "remote_url": "https://example.test/generated.mp4",
                    "media_type": "video",
                    "try_count": 0,
                    "max_try": 3,
                }
            )
        )

    assert terminal_updates == []


@pytest.mark.parametrize(
    ("upstream_url", "cached_url", "expected_input_url", "media_type", "postprocessed_url"),
    [
        (
            "/upload/cache/local.mp4",
            None,
            "/upload/cache/local.mp4",
            "video",
            "/upload/cache/local.face_grid_trimmed.mp4",
        ),
        (
            "https://example.test/generated.mp4",
            "/upload/cache/downloaded.mp4",
            "/upload/cache/downloaded.mp4",
            "video",
            "/upload/cache/downloaded.face_grid_trimmed.mp4",
        ),
        (
            "https://example.test/generated.png",
            "/upload/cache/downloaded.png",
            "/upload/cache/downloaded.png",
            "image",
            "/upload/cache/downloaded.png",
        ),
        (
            "https://example.test/fallback.mp4",
            None,
            "https://example.test/fallback.mp4",
            "video",
            "https://example.test/fallback.mp4",
        ),
    ],
)
def test_visual_sync_mode_persists_postprocessed_result_before_completed(
    monkeypatch,
    upstream_url,
    cached_url,
    expected_input_url,
    media_type,
    postprocessed_url,
):
    """同步 driver 的本地、下载、图片和远程 fallback 都必须先经过统一服务。"""
    from task import mock_interceptor
    from task import pipeline_processor
    from task import visual_drivers
    from utils import media_cache

    updates = []
    postprocess_calls = []

    monkeypatch.setattr(mock_interceptor, "is_mock_enabled", lambda: False)
    monkeypatch.setattr(pipeline_processor.PipelineProcessor, "get_pending_steps", lambda *_: [])
    monkeypatch.setattr(visual_drivers.VideoDriverFactory, "get_implementation_for_user", lambda *_: None)
    driver = SimpleNamespace(
        driver_name="test-sync-driver",
        submit_task=lambda _ai_tool: {
            "success": True,
            "sync_mode": True,
            "result_url": upstream_url,
        },
    )
    monkeypatch.setattr(visual_drivers.VideoDriverFactory, "create_driver_by_type", lambda *_args, **_kwargs: driver)

    async def fake_download(*_args, **_kwargs):
        return cached_url

    async def fake_postprocess(*, ai_tool_id, result_url, media_type):
        postprocess_calls.append((ai_tool_id, result_url, media_type))
        return SimpleNamespace(result_url=postprocessed_url)

    monkeypatch.setattr(media_cache, "download_and_cache", fake_download)
    monkeypatch.setattr(
        visual_task,
        "maybe_trim_generated_face_grid_prefix",
        fake_postprocess,
        raising=False,
    )
    monkeypatch.setattr(visual_task.AIToolsModel, "update", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        visual_task.AIToolsModel,
        "update_with_cdn_sync",
        lambda _task_id, **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(visual_task.TasksModel, "update_by_task_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(visual_task.AIToolsLogModel, "log", lambda *_args, **_kwargs: None)
    _patch_attempt_completion(monkeypatch)

    ai_tool = SimpleNamespace(id=801, type=21, user_id=51, implementation=None)

    assert asyncio.run(visual_task._submit_new_task(ai_tool)) is True
    assert postprocess_calls == [(801, expected_input_url, media_type)]
    assert _result_url_from_update(updates) == postprocessed_url


def _patch_visual_success_dependencies(monkeypatch):
    final_updates = []
    task_logs = []

    monkeypatch.setattr(
        visual_task.AIToolsModel,
        "update_by_project_id",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        visual_task.AIToolsModel,
        "update_by_project_id_with_cdn_sync",
        lambda **kwargs: final_updates.append(kwargs),
    )
    monkeypatch.setattr(visual_task.TasksModel, "update_by_task_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        visual_task.AIToolsLogModel,
        "log",
        lambda _task_id, _event, **kwargs: task_logs.append(kwargs),
    )
    monkeypatch.setattr(
        visual_task.RunningHubSlotsModel,
        "release_slot_by_project_id",
        lambda *_: None,
    )
    _patch_attempt_completion(monkeypatch)
    return final_updates, task_logs


def test_visual_async_local_result_is_postprocessed_before_terminal_update(monkeypatch):
    """异步轮询返回本地结果时，直接写入会绕过裁剪服务。"""
    postprocess_calls = []
    final_updates, task_logs = _patch_visual_success_dependencies(monkeypatch)

    async def fake_postprocess(*, ai_tool_id, result_url, media_type):
        postprocess_calls.append((ai_tool_id, result_url, media_type))
        return SimpleNamespace(result_url="/upload/cache/local.face_grid_trimmed.mp4")

    monkeypatch.setattr(
        visual_task,
        "maybe_trim_generated_face_grid_prefix",
        fake_postprocess,
        raising=False,
    )

    assert asyncio.run(
        visual_task._handle_task_success("project-901", 901, "/upload/cache/local.mp4")
    ) is True

    assert postprocess_calls == [(901, "/upload/cache/local.mp4", "video")]
    assert _result_url_from_update(final_updates) == "/upload/cache/local.face_grid_trimmed.mp4"
    assert task_logs[-1]["detail"]["result_url"] == "/upload/cache/local.face_grid_trimmed.mp4"


def test_visual_async_enqueue_failure_postprocesses_download_fallback_once(monkeypatch):
    """入队异常的同步下载 fallback 若不接服务，会把未裁剪缓存 URL 写入终态。"""
    from model.download_queue import DownloadQueueModel
    from utils import media_cache

    postprocess_calls = []
    completion_order = []
    final_updates, task_logs = _patch_visual_success_dependencies(monkeypatch)

    monkeypatch.setattr(DownloadQueueModel, "enqueue", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("db down")))

    async def fake_download(*_args, **_kwargs):
        return "/upload/cache/fallback.mp4"

    async def fake_postprocess(*, ai_tool_id, result_url, media_type):
        completion_order.append("postprocess")
        postprocess_calls.append((ai_tool_id, result_url, media_type))
        return SimpleNamespace(result_url="/upload/cache/fallback.face_grid_trimmed.mp4")

    monkeypatch.setattr(media_cache, "download_and_cache", fake_download)
    monkeypatch.setattr(
        visual_task,
        "maybe_trim_generated_face_grid_prefix",
        fake_postprocess,
        raising=False,
    )
    monkeypatch.setattr(
        visual_task.TasksModel,
        "update_by_task_id",
        lambda _task_id, **kwargs: (
            completion_order.append("task_completed")
            if kwargs.get("status") == visual_task.TASK_STATUS_COMPLETED
            else None
        ),
    )

    assert asyncio.run(
        visual_task._handle_task_success(
            "project-902",
            902,
            "https://example.test/generated.mp4",
        )
    ) is True

    assert postprocess_calls == [(902, "/upload/cache/fallback.mp4", "video")]
    assert completion_order == ["postprocess", "task_completed"]
    assert _result_url_from_update(final_updates) == "/upload/cache/fallback.face_grid_trimmed.mp4"
    assert task_logs[-1]["detail"]["result_url"] == "/upload/cache/fallback.face_grid_trimmed.mp4"


def test_visual_async_successful_enqueue_defers_postprocess_to_download_worker(monkeypatch):
    """成功入队后若 visual_task 也处理，会对同一视频生成两个不同裁剪 URL。"""
    from model.download_queue import DownloadQueueModel, ENQUEUE_NEW

    final_updates, _task_logs = _patch_visual_success_dependencies(monkeypatch)
    monkeypatch.setattr(DownloadQueueModel, "enqueue", lambda **_kwargs: ENQUEUE_NEW)

    async def forbidden_postprocess(**_kwargs):
        pytest.fail("成功入队后只能由 download worker 后处理")

    monkeypatch.setattr(
        visual_task,
        "maybe_trim_generated_face_grid_prefix",
        forbidden_postprocess,
        raising=False,
    )

    assert asyncio.run(
        visual_task._handle_task_success(
            "project-903",
            903,
            "https://example.test/generated.mp4",
        )
    ) is True
    assert final_updates == []


@pytest.mark.parametrize(
    ("upstream_url", "cached_url", "expected_input_url", "media_type", "postprocessed_url"),
    [
        (
            "/upload/cache/local.mp4",
            None,
            "/upload/cache/local.mp4",
            "video",
            "/upload/cache/local.face_grid_trimmed.mp4",
        ),
        (
            "https://example.test/generated.mp4",
            "/upload/cache/downloaded.mp4",
            "/upload/cache/downloaded.mp4",
            "video",
            "/upload/cache/downloaded.face_grid_trimmed.mp4",
        ),
        (
            "https://example.test/generated.png",
            "/upload/cache/downloaded.png",
            "/upload/cache/downloaded.png",
            "image",
            "/upload/cache/downloaded.png",
        ),
        (
            "https://example.test/fallback.mp4",
            None,
            "https://example.test/fallback.mp4",
            "video",
            "https://example.test/fallback.mp4",
        ),
    ],
)
def test_sync_worker_postprocesses_final_worker_result(
    monkeypatch,
    upstream_url,
    cached_url,
    expected_input_url,
    media_type,
    postprocessed_url,
):
    """同步服务必须在实际执行/下载 worker 内运行，而不是结果调度线程。"""
    import model
    from task import mock_interceptor
    from task import visual_drivers
    from utils import media_cache

    postprocess_calls = []
    ai_tool = SimpleNamespace(
        id=1001,
        type=21,
        user_id=61,
        implementation=None,
    )
    monkeypatch.setattr(mock_interceptor, "is_mock_enabled", lambda: False)
    monkeypatch.setattr(model.AIToolsModel, "update", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(model.AIToolsModel, "get_by_id", lambda *_: ai_tool)
    monkeypatch.setattr(model.TasksModel, "update_by_task_id", lambda *_args, **_kwargs: None)
    driver = SimpleNamespace(
        driver_name="test-sync-worker-driver",
        submit_task=lambda _ai_tool: {
            "success": True,
            "sync_mode": True,
            "result_url": upstream_url,
        },
    )
    monkeypatch.setattr(visual_drivers.VideoDriverFactory, "create_driver_by_type", lambda *_args, **_kwargs: driver)

    async def fake_download(*_args, **_kwargs):
        return cached_url

    def fake_postprocess(*, ai_tool_id, result_url, media_type):
        postprocess_calls.append((ai_tool_id, result_url, media_type))
        return SimpleNamespace(result_url=postprocessed_url)

    monkeypatch.setattr(media_cache, "download_and_cache", fake_download)
    monkeypatch.setattr(
        postprocess_service,
        "maybe_trim_generated_face_grid_prefix_sync",
        fake_postprocess,
    )

    result = sync_task_executor._execute_sync_task(task_id=1001, ai_tool_type=21)

    assert result.success is True
    assert result.result_url == postprocessed_url
    assert postprocess_calls == [(1001, expected_input_url, media_type)]


def test_sync_result_handler_only_persists_worker_result(monkeypatch):
    """在调度线程的 handler 再调用同步服务会阻塞结果分发并重复裁剪。"""
    import model

    updates = []
    monkeypatch.setattr(
        postprocess_service,
        "maybe_trim_generated_face_grid_prefix_sync",
        lambda **_kwargs: pytest.fail("结果 handler 不得运行视频后处理"),
    )
    monkeypatch.setattr(
        model.AIToolsModel,
        "update_with_cdn_sync",
        lambda _task_id, **kwargs: updates.append(kwargs),
    )
    monkeypatch.setattr(model.TasksModel, "update_by_task_id", lambda *_args, **_kwargs: None)
    _patch_attempt_completion(monkeypatch)

    executor = sync_task_executor.SyncTaskExecutor()
    executor._handle_task_result(
        sync_task_executor.SyncTaskResult(
            task_id=1002,
            ai_tool_type=21,
            success=True,
            result_url="/upload/cache/already-postprocessed.mp4",
        )
    )

    assert _result_url_from_update(updates) == "/upload/cache/already-postprocessed.mp4"


def test_download_lease_covers_download_postprocess_and_completion_margin():
    """租约短于下载、视频后处理和落库总预算会导致同一行被并发回收。"""
    required_seconds = (
        constant.DOWNLOAD_PER_ATTEMPT_TIMEOUT
        + constant.GeneratedVideoFaceGridTrimConstants.MAX_PROCESSING_SECONDS
        + constant.DOWNLOAD_COMPLETION_MARGIN_SECONDS
    )

    assert constant.DOWNLOAD_LEASE_SECONDS > required_seconds
