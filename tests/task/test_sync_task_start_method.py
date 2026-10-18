"""sync worker 进程池启动方式（spawn 默认 + 动态配置回退）测试。

背景（docs/backend/sync_worker_spawn_cutover.md）：fork 继承的模块级线程池在
worker 内"有账无线程"，造成 2026-09-13 七牛上传 / 2026-10-18 seedream 下载写盘
的精确 30s/120s 假超时。默认切 spawn 根治，sync_task.worker_start_method 可回退。

覆盖：
1. _get_worker_start_method 解析：spawn/fork/大小写与空白/非法回退/无 fork 平台回退；
2. start() 与 _rebuild_pool_locked() 两处建池均传递正确 mp_context；
3. 真实 spawn worker 内 download_io_pool 可用（2026-10-18 事故场景的端到端回归）。
"""
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from unittest import TestCase

import task.sync_task_executor as ste
from config.constant import SYNC_WORKER_DEFAULT_START_METHOD

# spawn 拉起 + 子进程模块导入链可能较慢（对齐 test_sync_worker_driver_registry）
_PROBE_TIMEOUT_SECONDS = 180


def _fake_dynamic_config(value):
    from unittest import mock

    return mock.patch(
        "config.config_util.get_dynamic_config_value",
        side_effect=lambda *a, **k: value if a[:2] == ("sync_task", "worker_start_method") else k.get("default"),
    )


def _fresh_executor():
    """重置单例状态（对齐 test_sync_task_pool_reclaim.make_executor 范式）。"""
    executor = ste.SyncTaskExecutor()
    executor._running = False
    executor._executor = None
    executor._futures = {}
    executor._submit_times = {}
    executor._task_drivers = {}
    executor._task_types = {}
    executor._pool_broken = False
    executor._max_workers = 2
    return executor


class _CapturingPool:
    """捕获 mp_context 的假池（进程内 fake，不拉真子进程）。"""

    instances = []

    def __init__(self, **kwargs):
        self.captured = dict(kwargs)
        self._processes = {}
        _CapturingPool.instances.append(self)

    def shutdown(self, **kwargs):
        self._processes = None

    def submit(self, *args):
        raise AssertionError("本测试不应提交真实任务")


class TestWorkerStartMethodResolution(TestCase):

    def test_explicit_spawn(self):
        with _fake_dynamic_config("spawn"):
            self.assertEqual(ste.SyncTaskExecutor._get_worker_start_method(), "spawn")

    def test_explicit_fork_on_fork_platform(self):
        if "fork" not in multiprocessing.get_all_start_methods():
            self.skipTest("平台不支持 fork")
        with _fake_dynamic_config("fork"):
            self.assertEqual(ste.SyncTaskExecutor._get_worker_start_method(), "fork")

    def test_normalizes_case_and_whitespace(self):
        if "fork" not in multiprocessing.get_all_start_methods():
            self.skipTest("平台不支持 fork")
        with _fake_dynamic_config("  Fork  "):
            self.assertEqual(ste.SyncTaskExecutor._get_worker_start_method(), "fork")

    def test_invalid_value_falls_back_to_default(self):
        with _fake_dynamic_config("bogus"):
            self.assertEqual(
                ste.SyncTaskExecutor._get_worker_start_method(),
                SYNC_WORKER_DEFAULT_START_METHOD,
            )

    def test_none_uses_default(self):
        with _fake_dynamic_config(None):
            self.assertEqual(
                ste.SyncTaskExecutor._get_worker_start_method(),
                SYNC_WORKER_DEFAULT_START_METHOD,
            )

    def test_fork_on_no_fork_platform_falls_back_to_spawn(self):
        from unittest import mock

        with _fake_dynamic_config("fork"), mock.patch.object(
            ste.multiprocessing, "get_all_start_methods", lambda: ["spawn"]
        ):
            self.assertEqual(ste.SyncTaskExecutor._get_worker_start_method(), "spawn")


class TestEnvVarOverride(TestCase):
    """环境变量 SYNC_TASK_WORKER_START_METHOD：部署层应急开关，优先级最高。"""

    ENV_KEY = "SYNC_TASK_WORKER_START_METHOD"

    def test_env_overrides_dynamic_config(self):
        if "fork" not in multiprocessing.get_all_start_methods():
            self.skipTest("平台不支持 fork")
        from unittest import mock

        with mock.patch.dict(os.environ, {self.ENV_KEY: "fork"}), \
                _fake_dynamic_config("spawn"):
            self.assertEqual(ste.SyncTaskExecutor._get_worker_start_method(), "fork")

    def test_invalid_env_falls_back_to_default(self):
        from unittest import mock

        with mock.patch.dict(os.environ, {self.ENV_KEY: "bogus"}), \
                _fake_dynamic_config("fork"):
            # 环境变量非法时不吃掉合法的动态配置值
            self.assertEqual(
                ste.SyncTaskExecutor._get_worker_start_method(), "fork"
            )

    def test_unset_env_uses_dynamic_config(self):
        from unittest import mock

        env = {k: v for k, v in os.environ.items() if k != self.ENV_KEY}
        with mock.patch.dict(os.environ, env, clear=True), \
                _fake_dynamic_config("spawn"):
            self.assertEqual(ste.SyncTaskExecutor._get_worker_start_method(), "spawn")


class TestPoolConstructionPassesContext(TestCase):

    def setUp(self):
        _CapturingPool.instances = []
        self.executor = _fresh_executor()

    def tearDown(self):
        self.executor._running = False
        self.executor._executor = None

    def test_start_passes_spawn_context_by_default(self):
        with _fake_dynamic_config("spawn"), mock_patch_pool():
            self.assertTrue(self.executor.start())
        self.assertEqual(len(_CapturingPool.instances), 1)
        ctx = _CapturingPool.instances[0].captured.get("mp_context")
        self.assertIsNotNone(ctx, "start() 必须显式传递 mp_context")
        self.assertEqual(ctx.get_start_method(), "spawn")
        self.assertTrue(self.executor._running)

    def test_rebuild_passes_configured_context(self):
        if "fork" not in multiprocessing.get_all_start_methods():
            self.skipTest("平台不支持 fork")
        # 旧池：shutdown 后 _processes=None，回收快照走调用前路径
        old = _CapturingPool()
        old._processes = {}
        self.executor._executor = old
        self.executor._pool_broken = True
        self.executor._running = True
        with _fake_dynamic_config("fork"), mock_patch_pool():
            self.executor._rebuild_pool_locked()
        new_pools = [p for p in _CapturingPool.instances if p is not old]
        self.assertEqual(len(new_pools), 1, "rebuild 必须新建池")
        ctx = new_pools[0].captured.get("mp_context")
        self.assertIsNotNone(ctx, "rebuild 必须显式传递 mp_context")
        self.assertEqual(ctx.get_start_method(), "fork")


class TestSpawnWorkerDownloadPoolWorks(TestCase):
    """2026-10-18 事故端到端回归：spawn worker 内 download_io_pool 必须可用。

    fork 模式下 worker 继承父进程用过的池 → submit 永不被执行 → 精确 30s 假超时；
    spawn 模式下 worker 是全新解释器，池为进程内新建，submit 秒回。
    """

    def test_spawn_worker_download_io_pool_submits_instantly(self):
        pid, value = _spawn_probe_download_pool()
        self.assertNotEqual(pid, os.getpid(), "探针必须运行在独立 worker 进程")
        self.assertEqual(value, 42)


def _probe_download_pool():
    import os

    from utils.download_io_pool import get_download_io_executor

    fut = get_download_io_executor().submit(lambda: 42)
    return os.getpid(), fut.result(timeout=15)  # R4 红线：显式超时


def _spawn_probe_download_pool():
    ctx = multiprocessing.get_context("spawn")
    executor = ProcessPoolExecutor(max_workers=1, mp_context=ctx)
    try:
        future = executor.submit(_probe_download_pool)
        return future.result(timeout=_PROBE_TIMEOUT_SECONDS)
    finally:
        executor.shutdown(wait=False)


def mock_patch_pool():
    from unittest import mock

    return mock.patch.object(ste, "ProcessPoolExecutor", _CapturingPool)


if __name__ == "__main__":
    unittest.main()
