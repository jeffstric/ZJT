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


def test_worker_init_resets_inherited_storage_singleton(monkeypatch):
    """worker 初始化必须清掉 fork 继承来的存储单例（事故 2026-09-13 任务 47603）。

    Linux fork 模式下，父进程用过的 QiniuFileStorage 单例连着 ThreadPoolExecutor，
    其空闲信号量假 token 与 _threads 死对象一并被 fork 快照进子进程：子进程首个
    上传 submit 消费假 token 后跳过建线程，任务入队无人消费，精确 120 秒报
    "图片上传到CDN超时"且七牛日志连"开始上传文件"都没有。`_enterprise_sync_worker_init`
    必须清空工厂单例缓存（放在社区版 early-return 之前），子进程首次
    get_file_storage() 才会新建干净线程池。进程池默认已切 spawn，本重置是动态
    配置回退 fork 时的防线。

    断言方式为效果而非调用：预塞哨兵实例模拟 fork 继承的毒化单例，
    init 之后缓存必须为空——删除调用、把 reset_file_storage 改成空函数
    都会被抓住。
    """
    from utils.file_storage import factory as storage_factory

    _fresh_event()
    monkeypatch.setattr(ste, "SYNC_WORKER_INIT_WATCHDOG_TIMEOUT", 30)
    storage_factory._storage_instances["inherited-poison"] = object()

    ste._enterprise_sync_worker_init()

    assert "inherited-poison" not in storage_factory._storage_instances
    assert ste._sync_worker_init_done.is_set()


def test_worker_init_registers_video_drivers(monkeypatch):
    """worker 初始化必须自行注册视频驱动（事故 2026-09-20 任务 230）。

    spawn 子进程是全新解释器、不继承父进程内存，VideoDriverFactory._registered_drivers
    在 worker 里是空字典，sync_mode 任务必然报 "Driver implementation not
    registered"（误导文案"不支持的任务类型: 16"）。主进程只在 server.py 启动时
    register_all_drivers()，`_enterprise_sync_worker_init` 必须自行注册，且放在
    社区版 early-return 之前两版通吃。

    断言方式为效果而非调用：清空注册表模拟 spawn 空表起点，init 之后必须
    非空——删除调用、把 register_all_drivers 改成空函数都会被抓住。
    真实 spawn 进程级验证另见 test_sync_worker_driver_registry.py。
    """
    from task.visual_drivers import VideoDriverFactory, register_all_drivers

    _fresh_event()
    monkeypatch.setattr(ste, "SYNC_WORKER_INIT_WATCHDOG_TIMEOUT", 30)
    VideoDriverFactory._registered_drivers.clear()
    try:
        ste._enterprise_sync_worker_init()
        assert VideoDriverFactory._registered_drivers, (
            "worker init 后驱动注册表为空，sync_mode 任务将复现 2026-09-20 必败"
        )
    finally:
        # 幂等重建注册表，不把空表/半表留给同进程后续测试
        register_all_drivers()
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
