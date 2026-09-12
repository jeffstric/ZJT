"""SyncTaskExecutor 旧池 worker 回收的单元测试。

背景：ProcessPoolExecutor 池 broken 后 rebuild，shutdown(wait=False) 无法通知
卡死在废弃 call queue 上的 worker 退出——worker 进程与旧池队列管道随每次重建
累积，最终打满 FD 上限（事故 2026-09-12：scheduler 重建 46 次后累积 996 根
管道、360 个卡死 worker，EMFILE 全进程崩溃）。
"""

from task import sync_task_executor as ste
from config.constant import (
    SYNC_WORKER_RECLAIM_GRACE_SECONDS,
    SYNC_WORKER_RECLAIM_JOIN_TIMEOUT,
)


class FakeWorkerProcess:
    """Process 替身：terminate/kill/join 全记录，death 由用例控制。

    默认 SIGTERM 即死（真实池 worker 对 SIGTERM 走默认处置）；
    stubborn=True 模拟忽略 SIGTERM 的卡死 worker，需 SIGKILL 才退出。
    """

    def __init__(self, alive=True, stubborn=False, terminate_error=None):
        self._initially_alive = alive
        self._stubborn = stubborn
        self._terminate_error = terminate_error
        self.joined_with = []
        self.terminate_calls = 0
        self.kill_calls = 0

    def is_alive(self):
        if not self._initially_alive:
            return False
        if self.kill_calls:
            return False
        if self.terminate_calls and not self._stubborn:
            return False
        return True

    def terminate(self):
        if self._terminate_error is not None:
            raise self._terminate_error
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1

    def join(self, timeout=None):
        self.joined_with.append(timeout)


class FakePoolExecutor:
    """仅暴露 _processes / shutdown / submit 的最小 Executor 替身。"""

    def __init__(self, processes=None, *args, **kwargs):
        self._processes = processes if processes is not None else {}
        self.shutdown_calls = []
        self.submitted = []

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdown_calls.append((wait, cancel_futures))

    def submit(self, *args):
        self.submitted.append(args)

        class PendingFuture:
            def done(self):
                return False

        return PendingFuture()


def make_executor():
    executor = ste.SyncTaskExecutor()
    executor._running = True
    executor._executor = None
    executor._futures = {}
    executor._submit_times = {}
    executor._task_drivers = {}
    executor._task_types = {}
    executor._worker_pids = {}
    executor._pool_broken = True
    return executor


# ==================== rebuild 路径 ====================

def test_rebuild_terminates_and_reaps_workers(monkeypatch):
    executor = make_executor()
    cooperative = FakeWorkerProcess(alive=True)          # SIGTERM 即死
    stubborn = FakeWorkerProcess(alive=True, stubborn=True)  # 需 SIGKILL
    dead = FakeWorkerProcess(alive=False)
    old = FakePoolExecutor({100: cooperative, 101: stubborn, 102: dead})
    executor._executor = old
    monkeypatch.setattr(ste, "ProcessPoolExecutor", FakePoolExecutor)

    executor._rebuild_pool_locked()

    # 合作 worker：SIGTERM 生效，join 宽限收尸，无需 SIGKILL
    assert cooperative.terminate_calls == 1
    assert cooperative.kill_calls == 0
    assert cooperative.joined_with == [SYNC_WORKER_RECLAIM_GRACE_SECONDS]
    # 顽固 worker：SIGTERM 无效后 SIGKILL 兜底，两次 join
    assert stubborn.terminate_calls == 1
    assert stubborn.kill_calls == 1
    assert stubborn.joined_with == [
        SYNC_WORKER_RECLAIM_GRACE_SECONDS,
        SYNC_WORKER_RECLAIM_JOIN_TIMEOUT,
    ]
    # 已死 worker：不终止，仅防御性 join 收尸
    assert dead.terminate_calls == 0
    assert dead.joined_with == [SYNC_WORKER_RECLAIM_JOIN_TIMEOUT]
    assert executor._pool_broken is False
    assert executor._executor is not old


def test_rebuild_tolerates_executor_without_processes_attribute(monkeypatch):
    executor = make_executor()

    class BareExecutor:
        def shutdown(self, wait=True, cancel_futures=False):
            pass

    executor._executor = BareExecutor()
    monkeypatch.setattr(ste, "ProcessPoolExecutor", FakePoolExecutor)

    executor._rebuild_pool_locked()

    assert executor._pool_broken is False
    assert isinstance(executor._executor, FakePoolExecutor)


def test_rebuild_survives_per_worker_reclaim_error(monkeypatch):
    executor = make_executor()
    alive = FakeWorkerProcess(
        alive=True, terminate_error=RuntimeError("terminate failed")
    )
    old = FakePoolExecutor({300: alive})
    executor._executor = old
    monkeypatch.setattr(ste, "ProcessPoolExecutor", FakePoolExecutor)

    executor._rebuild_pool_locked()

    # 单个 worker 终止失败不阻断重建，池必须照常可用（kill 兜底路径继续走）
    assert executor._pool_broken is False
    assert isinstance(executor._executor, FakePoolExecutor)
    assert alive.kill_calls == 1


def test_submit_on_broken_pool_reclaims_old_workers_then_resubmits(monkeypatch):
    """submit 触发 rebuild 的完整链路：旧 worker 必须被回收，不能再依赖
    shutdown(wait=False) 留下卡死进程。"""
    executor = make_executor()
    alive = FakeWorkerProcess(alive=True)
    old = FakePoolExecutor({400: alive})
    executor._executor = old
    monkeypatch.setattr(ste, "ProcessPoolExecutor", FakePoolExecutor)

    assert executor.submit(500, 16, "seedream5_volcengine_v1") is True

    assert old.shutdown_calls == [(False, True)]
    assert alive.terminate_calls == 1
    assert executor._task_drivers[500] == "seedream5_volcengine_v1"
    assert 500 in executor._futures


# ==================== shutdown 路径 ====================

def test_shutdown_broken_pool_avoids_blocking_join(monkeypatch):
    """broken 池 + wait=True：必须走非阻塞 shutdown，否则 cleanup 永久挂死
    在 join 卡死 worker 上（真实 ProcessPoolExecutor.shutdown(wait=True) 语义），
    后续显式回收也永远执行不到。"""
    executor = make_executor()
    stuck = FakeWorkerProcess(alive=True, stubborn=True)
    pool = FakePoolExecutor({200: stuck})
    executor._executor = pool

    executor.shutdown(wait=True)

    assert pool.shutdown_calls == [(False, True)]
    assert stuck.kill_calls == 1
    assert executor._executor is None
    assert executor._running is False


def test_shutdown_healthy_pool_keeps_graceful_wait():
    """健康池 + wait=True：保持原有优雅语义（等任务跑完），回收仅收尸兜底。"""
    executor = make_executor()
    executor._pool_broken = False
    exited = FakeWorkerProcess(alive=False)  # 健康池 worker 随 shutdown 已退出
    pool = FakePoolExecutor({201: exited})
    executor._executor = pool

    executor.shutdown(wait=True)

    assert pool.shutdown_calls == [(True, False)]
    assert exited.terminate_calls == 0
    assert exited.joined_with == [SYNC_WORKER_RECLAIM_JOIN_TIMEOUT]
    assert executor._executor is None


def test_shutdown_skips_when_not_running():
    executor = make_executor()
    executor._running = False
    pool = FakePoolExecutor({202: FakeWorkerProcess(alive=True)})
    executor._executor = pool

    executor.shutdown(wait=True)

    assert pool.shutdown_calls == []
    assert executor._executor is pool
