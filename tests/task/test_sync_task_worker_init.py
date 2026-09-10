"""SyncTaskExecutor worker 初始化看门狗与死 worker 清理的单元测试。

背景：fork 只复制调用线程但复制所有锁的状态，initializer 卡死的 worker 会
永久占用进程池名额（事故 2026-09-08：12 个 worker 中 11 个死锁）。
"""

import logging
import threading

from task import sync_task_executor as ste


class FakeHandler(logging.Handler):
    def __init__(self):
        # Handler.__init__ 内部就会调用 createLock，计数必须先初始化
        self.create_lock_calls = 0
        super().__init__()

    def createLock(self):
        self.create_lock_calls += 1
        super().createLock()

    def emit(self, record):
        pass


class FakeProcess:
    def __init__(self, alive):
        self._alive = alive
        self.is_alive_calls = 0

    def is_alive(self):
        self.is_alive_calls += 1
        return self._alive


class FakePoolExecutor:
    """仅暴露 _processes 的最小 Executor 替身。"""

    def __init__(self, processes=None):
        if processes is None:
            processes = {}
        self._processes = processes

    def submit(self, *args):
        raise AssertionError("submit 不应被测试直接触达")


def _fresh_event():
    ste._sync_worker_init_done.clear()


def test_reset_inherited_logging_locks_rebuilds_every_handler_once():
    _fresh_event()
    fake = FakeHandler()
    root = logging.getLogger()
    named = logging.getLogger("sync-worker-init-test")
    old_handlers = root.handlers[:]
    old_named = named.handlers[:]
    root.handlers = [fake]
    named.handlers = [fake]
    try:
        # 同一次调用内 root/具名 logger 双通道注册同一 handler 只重建一次；
        # 去重作用域为单次调用，跨调用各处理一次是预期行为
        calls_before = fake.create_lock_calls
        ste._reset_inherited_logging_locks()
        first_call_increment = fake.create_lock_calls - calls_before
        calls_before = fake.create_lock_calls
        ste._reset_inherited_logging_locks()
        second_call_increment = fake.create_lock_calls - calls_before
    finally:
        root.handlers = old_handlers
        named.handlers = old_named

    assert first_call_increment == 1
    assert second_call_increment == 1


def test_worker_init_sets_done_event_on_community_shortcut(monkeypatch):
    _fresh_event()
    monkeypatch.setattr(ste, "SYNC_WORKER_INIT_WATCHDOG_TIMEOUT", 30)

    ste._enterprise_sync_worker_init()

    # 社区版短路 return 也要经过 finally，保证看门狗解除
    assert ste._sync_worker_init_done.is_set()


def test_start_init_watchdog_exits_when_init_never_completes(monkeypatch):
    _fresh_event()
    exited = []
    monkeypatch.setattr(ste.os, "_exit", lambda code: exited.append(code))
    monkeypatch.setattr(ste, "SYNC_WORKER_INIT_WATCHDOG_TIMEOUT", 0.05)

    ste._start_init_watchdog()
    threading.Event().wait(1)

    assert exited == [70]
    _fresh_event()


def test_purge_dead_workers_removes_dead_keeps_alive(monkeypatch):
    executor = ste.SyncTaskExecutor()
    executor._running = True
    executor._executor = FakePoolExecutor(
        {111: FakeProcess(alive=False), 222: FakeProcess(alive=True)}
    )
    executor._pool_broken = False

    executor._purge_dead_workers_locked()

    assert 111 not in executor._executor._processes
    assert 222 in executor._executor._processes
    assert executor._pool_broken is False


def test_purge_dead_workers_all_dead_marks_pool_broken():
    executor = ste.SyncTaskExecutor()
    executor._running = True
    executor._executor = FakePoolExecutor({111: FakeProcess(alive=False)})
    executor._pool_broken = False

    executor._purge_dead_workers_locked()

    assert executor._executor._processes == {}
    assert executor._pool_broken is True


def test_purge_dead_workers_tolerates_missing_processes():
    executor = ste.SyncTaskExecutor()
    executor._running = True
    executor._executor = FakePoolExecutor()
    executor._pool_broken = False

    # 无 _processes 内容时不应抛错、也不应误标 broken
    executor._purge_dead_workers_locked()

    assert executor._pool_broken is False
