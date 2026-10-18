"""download_io_pool pid 守卫回归测试（事故 2026-10-18，zjt_trial task 1186）。

根因：模块级 ThreadPoolExecutor 被 fork 继承进 sync worker 后，空闲信号量假
token + _threads 死对象使首个 submit 永不被执行，下载写盘连续精确 30s 假超时
（网络/磁盘实测均正常）。守卫语义：getter 检测 pid 漂移即重建池。

三层验证：
1. 同 pid 复用（长寿语义不变）；
2. pid 漂移（模拟 fork）→ 返回重建后的新池；
3. 真实 fork 子进程内，父进程"用过"（已毒化）的池经守卫修复后 submit 秒回。
"""
import multiprocessing
import os
import time
import unittest
from unittest import mock

import utils.download_io_pool as pool_mod
from utils.download_io_pool import get_download_io_executor

_HAS_FORK = "fork" in multiprocessing.get_all_start_methods()


class TestDownloadIoPoolPidGuard(unittest.TestCase):

    def tearDown(self):
        # 还原模块全局，避免影响其他用例
        pool_mod._DOWNLOAD_IO_EXECUTOR = None
        pool_mod._DOWNLOAD_IO_EXECUTOR_PID = None

    def test_same_pid_reuses_executor(self):
        first = get_download_io_executor()
        second = get_download_io_executor()
        self.assertIs(first, second, "同进程内必须是长寿复用语义")

    def test_pid_drift_rebuilds_executor(self):
        stale = object()  # 模拟 fork 继承进子进程的失效池
        pool_mod._DOWNLOAD_IO_EXECUTOR = stale  # type: ignore[assignment]
        pool_mod._DOWNLOAD_IO_EXECUTOR_PID = os.getpid() + 1
        rebuilt = get_download_io_executor()
        self.assertIsNot(rebuilt, stale, "pid 漂移必须丢弃继承池")
        self.assertEqual(pool_mod._DOWNLOAD_IO_EXECUTOR_PID, os.getpid())
        # 重建后的池在本进程内立即可用（R4 红线：result 显式超时）
        self.assertEqual(rebuilt.submit(lambda: 42).result(timeout=10), 42)

    @unittest.skipUnless(_HAS_FORK, "平台不支持 fork，跳过真实 fork 复现")
    def test_fork_child_gets_working_executor(self):
        """直接复现事故机制：父进程用热池（线程+空闲 token 已产生）后 fork，
        子进程内提交任务必须在守卫修复后立即执行，而非假超时。"""
        # 父进程先"用一用"池：制造真实线程与空闲信号量 token（毒化前置条件）
        warm = get_download_io_executor()
        self.assertEqual(warm.submit(lambda: 1).result(timeout=10), 1)

        ctx = multiprocessing.get_context("fork")

        def child(q):
            t0 = time.time()
            try:
                fut = get_download_io_executor().submit(lambda: 42)
                q.put(("ok", fut.result(timeout=10), round(time.time() - t0, 2)))
            except Exception as e:  # noqa: BLE001
                q.put(("fail", repr(e), round(time.time() - t0, 2)))

        q = ctx.Queue()
        p = ctx.Process(target=child, args=(q,))
        p.start()
        p.join(30)
        self.assertFalse(p.is_alive(), "子进程应已退出")
        status, value, elapsed = q.get_nowait()
        self.assertEqual(status, "ok", f"子进程内 submit 应立即可用，实际: {value}")
        self.assertEqual(value, 42)
        self.assertLess(elapsed, 5, f"守卫修复后子进程 submit 应秒回，实际 {elapsed}s")


if __name__ == "__main__":
    unittest.main()
