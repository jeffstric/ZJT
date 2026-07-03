import time

from task import sync_task_executor as ste


class PendingFuture:
    def done(self):
        return False

    def cancel(self):
        return False


class CompletedFuture:
    def __init__(self, result):
        self._result = result

    def done(self):
        return True

    def result(self, timeout=None):
        return self._result


class FakeExecutor:
    def __init__(self):
        self.shutdown_calls = []
        self.submitted = []

    def submit(self, *args):
        self.submitted.append(args)
        return PendingFuture()

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdown_calls.append((wait, cancel_futures))


class RecordingLock:
    def __init__(self):
        self.depth = 0
        self.events = []

    def __enter__(self):
        self.depth += 1
        self.events.append("enter")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.events.append("exit")
        self.depth -= 1
        return False


def make_executor(monkeypatch):
    executor = ste.SyncTaskExecutor()
    executor._running = True
    executor._executor = FakeExecutor()
    executor._futures = {}
    executor._submit_times = {}
    executor._task_drivers = {}
    executor._task_types = {}
    executor._worker_pids = {}
    executor._pool_broken = False
    monkeypatch.setattr(executor, "_terminate_worker_for_task", lambda task_id: True)
    return executor


def test_stale_whitelisted_future_is_failed_and_pool_marked_broken(monkeypatch):
    executor = make_executor(monkeypatch)
    handled = []
    executor._futures[101] = PendingFuture()
    executor._submit_times[101] = time.time() - 10
    executor._task_drivers[101] = "seedream5_volcengine_v1"
    executor._task_types[101] = 16
    monkeypatch.setattr(ste, "get_sync_task_stale_timeout", lambda driver: 1)
    monkeypatch.setattr(executor, "_handle_task_result", handled.append)

    executor.check_results()

    assert 101 not in executor._futures
    assert executor._pool_broken is True
    assert len(handled) == 1
    assert handled[0].task_id == 101
    assert handled[0].success is False
    assert "stale timeout" in handled[0].error


def test_non_whitelisted_future_is_not_killed(monkeypatch):
    executor = make_executor(monkeypatch)
    executor._futures[102] = PendingFuture()
    executor._submit_times[102] = time.time() - 10
    executor._task_drivers[102] = "gemini"
    executor._task_types[102] = 16
    monkeypatch.setattr(ste, "get_sync_task_stale_timeout", lambda driver: None)

    executor.check_results()

    assert 102 in executor._futures
    assert executor._pool_broken is False


def test_pool_rebuilds_before_submit_when_marked_broken(monkeypatch):
    executor = make_executor(monkeypatch)
    rebuild_calls = []
    monkeypatch.setattr(executor, "_rebuild_pool_locked", lambda: rebuild_calls.append(True))
    executor._pool_broken = True

    assert executor.submit(103, 16, "seedream5_volcengine_v1") is True

    assert rebuild_calls == [True]
    assert executor._task_drivers[103] == "seedream5_volcengine_v1"


def test_completed_future_result_uses_timeout_keyword(monkeypatch):
    result = ste.SyncTaskResult(task_id=104, ai_tool_type=16, success=True, result_url="ok")
    executor = make_executor(monkeypatch)
    executor._futures[104] = CompletedFuture(result)
    executor._task_drivers[104] = "seedream5_volcengine_v1"
    executor._task_types[104] = 16
    handled = []
    monkeypatch.setattr(executor, "_handle_task_result", handled.append)

    executor.check_results()

    assert handled == [result]
    assert 104 not in executor._futures


def test_completed_result_handler_exception_falls_back_to_failure(monkeypatch):
    result = ste.SyncTaskResult(task_id=105, ai_tool_type=16, success=True, result_url="ok")
    executor = make_executor(monkeypatch)
    executor._futures[105] = CompletedFuture(result)
    executor._task_drivers[105] = "seedream5_volcengine_v1"
    executor._task_types[105] = 16
    fallback_calls = []

    def broken_handler(_result):
        raise RuntimeError("cdn update failed")

    monkeypatch.setattr(executor, "_handle_task_result", broken_handler)
    monkeypatch.setattr(executor, "_handle_task_failure", lambda *args: fallback_calls.append(args))

    executor.check_results()

    assert 105 not in executor._futures
    assert fallback_calls == [(105, "cdn update failed", "SYSTEM", 16)]


def test_stale_worker_not_released_when_termination_and_cancel_fail(monkeypatch):
    executor = make_executor(monkeypatch)
    handled = []
    executor._futures[106] = PendingFuture()
    executor._submit_times[106] = time.time() - 10
    executor._task_drivers[106] = "seedream5_volcengine_v1"
    executor._task_types[106] = 16
    monkeypatch.setattr(ste, "get_sync_task_stale_timeout", lambda driver: 1)
    monkeypatch.setattr(executor, "_terminate_worker_for_task", lambda task_id: False)
    monkeypatch.setattr(executor, "_handle_task_result", handled.append)

    executor.check_results()

    assert 106 in executor._futures
    assert executor._pool_broken is False
    assert handled == []


def test_stale_detection_string_false_disables_kill(monkeypatch):
    executor = make_executor(monkeypatch)
    executor._futures[107] = PendingFuture()
    executor._submit_times[107] = time.time() - 10
    executor._task_drivers[107] = "seedream5_volcengine_v1"
    executor._task_types[107] = 16
    monkeypatch.setattr(ste, "get_sync_task_stale_timeout", lambda driver: 1)

    def fake_dynamic_config(section, key, default=None):
        assert (section, key) == ("sync_task", "stale_detection_enabled")
        return "false"

    monkeypatch.setattr("config.config_util.get_dynamic_config_value", fake_dynamic_config)

    executor.check_results()

    assert 107 in executor._futures
    assert executor._pool_broken is False


def test_force_release_uses_state_lock_and_handles_result_outside_lock(monkeypatch):
    executor = make_executor(monkeypatch)
    lock = RecordingLock()
    executor._state_lock = lock
    executor._futures[108] = PendingFuture()
    executor._submit_times[108] = time.time() - 10
    executor._task_drivers[108] = "seedream5_volcengine_v1"
    executor._task_types[108] = 16
    observations = []

    def fake_kill(task_id, driver, elapsed, refund=True):
        observations.append(("kill", lock.depth))
        executor._cleanup_task_metadata(task_id)
        return ste.SyncTaskResult(task_id=task_id, ai_tool_type=16, success=False, error="forced")

    def fake_handle(result):
        observations.append(("handle", lock.depth))

    monkeypatch.setattr(executor, "_kill_stale_worker", fake_kill)
    monkeypatch.setattr(executor, "_handle_task_result", fake_handle)

    assert executor.force_release_task(108, refund=True) is True

    assert lock.events == ["enter", "exit"]
    assert observations == [("kill", 1), ("handle", 0)]
