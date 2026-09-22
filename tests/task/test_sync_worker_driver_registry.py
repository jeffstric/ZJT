"""sync worker 进程池驱动注册回归测试（Windows spawn，事故 2026-09-20 任务 230）。

根因：ProcessPoolExecutor 的 Windows spawn 不继承父进程内存，
``VideoDriverFactory._registered_drivers`` 在 worker 里是空字典，
sync_mode 任务（seedream 等）驱动创建必败，报误导文案"不支持的任务类型: 16"。

修复：``_enterprise_sync_worker_init`` 在 worker 内补
``init_unified_config() + register_all_drivers()``（幂等，fork 场景无害）。

本测试用显式 spawn 上下文在三个平台还原同一语义：
- 对照组：无 initializer 的 spawned worker 注册表必须为空（证明测试
  真实还原了 spawn 语义——若驱动改为 import 时自动注册，此对照会失败）；
- 实验组：挂 _enterprise_sync_worker_init 的 spawned worker 注册表非空。
"""
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from unittest import TestCase

from task.sync_task_executor import _enterprise_sync_worker_init

# spawn 拉起 + 子进程全量导入（config/驱动模块链）可能较慢；
# 首次运行含解释器冷启动，给足余量（R4 红线：result 必须显式超时）
_PROBE_TIMEOUT_SECONDS = 180


def _probe_registered_driver_count():
    """在 worker 进程内读取驱动注册表大小（子进程内 import，读父进程状态无意义）。

    返回 (pid, count)：pid 供测试断言确实运行在独立进程，防止执行方式
    被改为进程内直跑后测试空转。"""
    import os

    from task.visual_drivers import VideoDriverFactory

    return os.getpid(), len(VideoDriverFactory._registered_drivers)


class TestSyncWorkerDriverRegistry(TestCase):
    """spawn worker 内 VideoDriverFactory 注册表必须有驱动。"""

    def _spawn_probe(self, initializer):
        ctx = multiprocessing.get_context("spawn")
        executor = ProcessPoolExecutor(
            max_workers=1, mp_context=ctx, initializer=initializer
        )
        try:
            future = executor.submit(_probe_registered_driver_count)
            return future.result(timeout=_PROBE_TIMEOUT_SECONDS)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

    def test_spawn_worker_without_initializer_has_empty_registry(self):
        """对照：spawn 子进程默认不继承注册表（还原事故现场）。"""
        pid, count = self._spawn_probe(initializer=None)
        self.assertNotEqual(pid, os.getpid(), "探针必须运行在独立子进程")
        self.assertEqual(
            count, 0,
            "spawn 子进程注册表应为空；若驱动改为 import 时自动注册，"
            "本对照与 _enterprise_sync_worker_init 的注册语义需重新评估",
        )

    def test_spawn_worker_init_registers_video_drivers(self):
        """核心回归：worker initializer 注册后注册表非空。"""
        pid, count = self._spawn_probe(initializer=_enterprise_sync_worker_init)
        self.assertNotEqual(pid, os.getpid(), "探针必须运行在独立子进程")
        self.assertGreater(
            count, 0,
            "sync worker 初始化后 VideoDriverFactory 注册表为空，"
            "sync_mode 任务将复现 2026-09-20 任务 230 的必败",
        )
