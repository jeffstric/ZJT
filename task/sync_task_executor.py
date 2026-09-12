#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
同步任务执行器 - 独立进程池处理同步API请求

将同步API请求（如Gemini、Seedream）从调度器主线程分流到独立进程池，
避免阻塞任务队列。
"""

import logging
import multiprocessing
import os
import sys
import time
import uuid
import threading
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, Future
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Dict, Optional, Any

from config.constant import (
    SYNC_WORKER_INIT_WATCHDOG_TIMEOUT,
    SYNC_WORKER_RECLAIM_GRACE_SECONDS,
    SYNC_WORKER_RECLAIM_JOIN_TIMEOUT,
    get_sync_task_stale_timeout,
)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# worker 子进程内：initializer 完成标志，看门狗据此判断初始化是否卡死。
# 父进程从不 set 它，fork 继承的是未触发状态，子进程内无死锁风险。
_sync_worker_init_done = threading.Event()


@dataclass
class SyncTaskResult:
    """Result returned by a sync task worker."""
    task_id: int
    ai_tool_type: int
    success: bool
    result_url: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None



def _reset_inherited_logging_locks() -> None:
    """重建 fork 继承的 logging 锁。必须在子进程任何日志调用之前执行。

    fork 只复制调用线程，但会复制所有锁的当前状态：若 fork 瞬间父进程其他
    线程正持有某把锁，子进程会继承一把永远无人释放的锁。CPython 仅对
    logging 自身注册了 at-fork 重置，覆盖不了其他基础设施的锁；这里防御性
    重建模块锁与全部 handler 锁，保证 initializer 内的日志调用永不因继承锁
    卡死（事故 2026-09-08：池 worker fork 后大面积死锁，卡死的七牛上传连
    HTTP 请求都未发出，上层只能等 120s 超时）。
    """
    logging._lock = threading.RLock()
    seen = set()
    handlers = list(logging.getLogger().handlers)
    for name in list(logging.root.manager.loggerDict):
        handlers.extend(getattr(logging.getLogger(name), "handlers", []))
    for handler in handlers:
        if id(handler) in seen:
            continue
        seen.add(id(handler))
        try:
            handler.createLock()
        except Exception:
            # 个别 handler 重建失败不阻断初始化；真正的卡死由看门狗兜底
            pass


def _start_init_watchdog() -> None:
    """initializer 看门狗：超时未完成初始化则强制退出当前 worker 进程。

    fork 继承的死锁无法逐一枚举重置（DB 连接池、第三方 SDK 内部锁等）。
    卡死的 worker 会永久占用进程池名额且自愈无门；看门狗超时自杀后，
    父进程 submit 路径的 _purge_dead_workers_locked() 会清理死亡进程，
    原生 _adjust_process_count 随即补 fork，形成自愈闭环。
    """

    def _watchdog() -> None:
        if not _sync_worker_init_done.wait(timeout=SYNC_WORKER_INIT_WATCHDOG_TIMEOUT):
            os._exit(70)

    threading.Thread(
        target=_watchdog,
        name="sync-worker-init-watchdog",
        daemon=True,
    ).start()


def _enterprise_sync_worker_init() -> None:
    """ProcessPool 子进程 initializer：注入商业 Provider + 许可证 runtime。

    子进程不继承父进程的 register_provider / _manager 等模块全局状态。
    未初始化时 face_mask 会静默走社区 skip，多密钥池也会退化为单密钥。

    顺序约束：锁重建必须先于一切日志调用；看门狗必须先于一切可能卡死的
    初始化步骤——fork 继承的死锁只有两种出口：主动重置 / 超时自杀。
    """
    _reset_inherited_logging_locks()
    _start_init_watchdog()
    try:
        from config.constant import Edition
        if Edition.is_community():
            return
        import enterprise

        enterprise.bootstrap_background_process(
            enable_background_refresh=False,
            include_failure_retry=False,
            include_marketing_tools=False,
        )
        logger.info(
            "[SyncTaskExecutor] enterprise background bootstrap done (pid=%s)",
            os.getpid(),
        )
    except Exception:
        logger.exception(
            "[SyncTaskExecutor] enterprise background bootstrap failed (pid=%s)",
            os.getpid(),
        )
    finally:
        _sync_worker_init_done.set()


def _execute_sync_task(task_id: int, ai_tool_type: int) -> SyncTaskResult:
    """
    子进程入口函数 - 执行同步任务

    ⚠️ 关键设计：此函数运行在独立子进程中（ProcessPoolExecutor），不能引用主进程的
    数据库连接、锁、或任何可变全局状态。每次调用都需要重新导入模块和初始化连接。

    ⚠️ 禁止把 multiprocessing.Manager 代理（或任何需要连接池外进程的对象）
    作为本函数参数传入：worker 端 unpickle 参数时必须连接 Manager 服务进程，
    Manager 一死所有任务在反序列化阶段就崩溃（2026-09-12 20:43 事故：
    SyncManager 启动后 3 分钟内死亡，生图任务 100% 失败，
    ConnectionRefusedError @ RebuildProxy._incref）。worker pid 靠下方日志观测。

    Args:
        task_id: AI工具ID
        ai_tool_type: AI工具类型

    Returns:
        SyncTaskResult: 任务执行结果
    """
    # ⚠️ 子进程必须重新导入所有模块，不能使用主进程的数据库连接和全局状态
    import asyncio
    from model import AIToolsModel, TasksModel
    from config.constant import (
        AI_TOOL_STATUS_PROCESSING,
        AI_TOOL_STATUS_COMPLETED,
        AI_TOOL_STATUS_FAILED,
        TASK_STATUS_PROCESSING,
        TASK_STATUS_COMPLETED,
        TASK_STATUS_FAILED,
    )

    logger.info(
        f"[SyncTask] Starting task {task_id} (type: {ai_tool_type}, worker pid: {os.getpid()})"
    )

    try:
        # 更新状态为处理中
        AIToolsModel.update(task_id, status=AI_TOOL_STATUS_PROCESSING)
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_PROCESSING)

        # ===== E2E Mock 短路（同步子进程，覆盖所有 13 个 sync_mode 实现）=====
        from task.mock_interceptor import is_mock_enabled, visual_sync_result
        if is_mock_enabled():
            mock = visual_sync_result(ai_tool_type)
            url = mock.get("result_url")
            if url:
                logger.info(f"[MOCK] visual sync short-circuit task={task_id} url={url}")
                return SyncTaskResult(
                    task_id=task_id, ai_tool_type=ai_tool_type,
                    success=True, result_url=url,
                )
        # ==================================================================

        # 获取AI工具详情
        ai_tool = AIToolsModel.get_by_id(task_id)
        if not ai_tool:
            logger.error(f"[SyncTask] Task {task_id} not found in database")
            return SyncTaskResult(
                task_id=task_id,
                ai_tool_type=ai_tool_type,
                success=False,
                error="task not found",
                error_type="SYSTEM"
            )

        # 调用驱动提交任务（同步执行）
        from task.visual_drivers import VideoDriverFactory
        from config.unified_config import get_implementation_name

        # 优先使用 ai_tools.implementation（如由 retry driver 设置），回退到用户偏好
        driver = None
        if ai_tool.implementation:
            impl_name = get_implementation_name(ai_tool.implementation)
            if impl_name and impl_name != 'unknown':
                driver = VideoDriverFactory.create_driver_by_implementation(impl_name)
                if driver:
                    logger.info(f"[SyncTask] Using recorded implementation {impl_name} (id: {ai_tool.implementation}) for task {task_id}")

        if not driver:
            driver = VideoDriverFactory.create_driver_by_type(ai_tool_type, user_id=ai_tool.user_id)
        if not driver:
            logger.error(f"[SyncTask] Unsupported driver type: {ai_tool_type}")
            return SyncTaskResult(
                task_id=task_id,
                ai_tool_type=ai_tool_type,
                success=False,
                error=f"不支持的任务类型: {ai_tool_type}",
                error_type="SYSTEM"
            )

        logger.info(f"[SyncTask] Using driver: {driver.driver_name} for task {task_id}")

        # 调用驱动提交任务
        import inspect
        if inspect.iscoroutinefunction(driver.submit_task):
            result = asyncio.run(driver.submit_task(ai_tool))
        else:
            result = driver.submit_task(ai_tool)

        # 处理提交结果
        if not result.get("success"):
            error = result.get("error", "unknown error")
            error_type = result.get("error_type", "SYSTEM")
            logger.error(f"[SyncTask] Task {task_id} failed: {error}")
            return SyncTaskResult(
                task_id=task_id,
                ai_tool_type=ai_tool_type,
                success=False,
                error=error,
                error_type=error_type
            )

        # 检查是否同步模式
        if result.get("sync_mode"):
            result_url = result.get("result_url")

            media_type = "video"
            if result_url:
                ext = result_url.split('?')[0].split('.')[-1].lower()
                if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    media_type = "image"

            # 判断是否已经是本地路径
            is_local_path = result_url and result_url.startswith("/upload/")

            if not is_local_path and result_url:
                # 下载并缓存媒体文件
                from utils.media_cache import download_and_cache

                # 下载并缓存
                cached_url = asyncio.run(download_and_cache(result_url, task_id, media_type))
                result_url = cached_url if cached_url else result_url

            from services.generated_video_face_grid_service import (
                maybe_trim_generated_face_grid_prefix_sync,
            )
            postprocess = maybe_trim_generated_face_grid_prefix_sync(
                ai_tool_id=task_id,
                result_url=result_url,
                media_type=media_type,
            )
            result_url = postprocess.result_url
            logger.info(f"[SyncTask] Task {task_id} completed with result: {result_url}")
            return SyncTaskResult(
                task_id=task_id,
                ai_tool_type=ai_tool_type,
                success=True,
                result_url=result_url
            )

        # 异步模式不应该出现在这里
        logger.error(f"[SyncTask] Task {task_id} returned async mode in sync executor")
        return SyncTaskResult(
            task_id=task_id,
            ai_tool_type=ai_tool_type,
            success=False,
            error="async mode task submitted to sync executor",
            error_type="SYSTEM"
        )

    except Exception as e:
        logger.error(f"[SyncTask] Exception in task {task_id}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return SyncTaskResult(
            task_id=task_id,
            ai_tool_type=ai_tool_type,
            success=False,
            error=str(e),
            error_type="SYSTEM"
        )


class SyncTaskExecutor:
    """
    同步任务执行器 - 单例模式

    管理进程池生命周期，处理同步API请求
    """
    _instance: Optional['SyncTaskExecutor'] = None
    _lock = multiprocessing.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return

        self._initialized = True
        self._executor: Optional[ProcessPoolExecutor] = None
        self._futures: Dict[int, Future] = {}  # task_id -> Future
        self._results: Dict[int, SyncTaskResult] = {}  # task_id -> result
        self._submit_times: Dict[int, float] = {}
        self._task_drivers: Dict[int, str] = {}
        self._task_types: Dict[int, int] = {}
        self._pool_broken = False
        self._running = False
        self._state_lock = threading.RLock()

        # 配置参数
        self._max_workers = self._get_max_workers()
        self._check_interval = self._get_check_interval()

    def _get_max_workers(self) -> int:
        """Return the configured maximum number of sync workers."""
        try:
            from config.config_util import get_dynamic_config_value
            return get_dynamic_config_value("sync_task", "max_workers", default=4)
        except Exception:
            return 4

    def _get_check_interval(self) -> int:
        """Return the result check interval in seconds."""
        try:
            from config.config_util import get_dynamic_config_value
            return get_dynamic_config_value("sync_task", "check_interval", default=5)
        except Exception:
            return 5

    def _is_stale_detection_enabled(self) -> bool:
        try:
            from config.config_util import get_dynamic_config_value

            value = get_dynamic_config_value("sync_task", "stale_detection_enabled", default=True)
            return self._parse_bool_config(value, default=True)
        except Exception:
            return True

    @staticmethod
    def _parse_bool_config(value, default: bool = True) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"", "0", "false", "no", "off", "none", "null"}:
                return False
            if normalized in {"1", "true", "yes", "on"}:
                return True
            return default
        return bool(value)

    def start(self) -> bool:
        """Start the sync task executor."""
        if self._running:
            logger.warning("[SyncTaskExecutor] Already running")
            return True

        try:
            # 不再使用 multiprocessing.Manager 共享 worker_pids：Manager 服务进程
            # 是单点，死亡后所有任务在 worker 端 unpickle 参数（RebuildProxy 连接）
            # 阶段崩溃（2026-09-12 20:43 事故，生图任务 100% 失败）。
            self._executor = ProcessPoolExecutor(
                max_workers=self._max_workers,
                initializer=_enterprise_sync_worker_init,
            )
            self._pool_broken = False
            self._running = True
            logger.info(f"[SyncTaskExecutor] Started with max_workers={self._max_workers}")
            return True
        except Exception as e:
            logger.error(f"[SyncTaskExecutor] Failed to start: {e}")
            return False

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the sync task executor."""
        if not self._running:
            return

        self._running = False

        if self._executor:
            # 必须先快照 _processes：CPython 的 shutdown() 无论 wait 与否都会
            # 把 _processes 置 None（源码注释"To reduce the risk of opening
            # too many files"），shutdown 后再取就是 None，回收会变空操作
            processes = list((getattr(self._executor, "_processes", None) or {}).items())
            if wait and not self._pool_broken:
                # 健康池：等任务跑完、worker 随 shutdown 正常退出
                self._executor.shutdown(wait=True)
            else:
                # broken 池：shutdown(wait=True) 会永久阻塞在 join 卡死 worker
                # 的路径上（worker 收不到退出通知），必须非阻塞关闭 + 显式回收，
                # 否则调度器 SIGTERM cleanup 挂死、进程与 FD 同样泄漏
                try:
                    self._executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    self._executor.shutdown(wait=False)
            # 健康池的 worker 已随 shutdown 退出，这里仅收尸兜底；broken 池的
            # 卡死 worker 必须显式终止，否则进程与管道 FD 泄漏
            with self._state_lock:
                reclaimed = self._reclaim_workers_locked(processes)
            if reclaimed:
                logger.warning(
                    "[SyncTaskExecutor] Reclaimed %d worker(s) on shutdown",
                    reclaimed,
                )
            self._executor = None

        self._futures.clear()
        self._submit_times.clear()
        self._task_drivers.clear()
        self._task_types.clear()
        self._pool_broken = False
        logger.info("[SyncTaskExecutor] Shutdown complete")

    def is_running(self) -> bool:
        """Return whether the executor is running."""
        return self._running and self._executor is not None

    def is_task_running(self, task_id: int) -> bool:
        """Return whether a task is tracked by this executor."""
        return task_id in self._futures
        return task_id in self._futures

    def _rebuild_pool_locked(self) -> None:
        old_executor = self._executor
        if old_executor:
            # 必须先快照 _processes：CPython 的 shutdown() 无论 wait 与否都会
            # 把 _processes 置 None，shutdown 后再取就是 None，回收会变空操作
            processes = list((getattr(old_executor, "_processes", None) or {}).items())
            try:
                old_executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                old_executor.shutdown(wait=False)
            except Exception as exc:
                logger.warning(f"[SyncTaskExecutor] Error shutting down broken pool: {exc}")
            # shutdown(wait=False) 依赖管理线程通知 worker 退出，broken 池做不到
            # （worker 卡死在废弃 call queue 上），必须显式回收旧 worker，
            # 否则进程与管道 FD 随每次重建累积（2026-09-12 EMFILE 事故根因之一）
            reclaimed = self._reclaim_workers_locked(processes)
            if reclaimed:
                logger.warning(
                    "[SyncTaskExecutor] Reclaimed %d worker(s) from the replaced pool",
                    reclaimed,
                )

        self._executor = ProcessPoolExecutor(
            max_workers=self._max_workers,
            initializer=_enterprise_sync_worker_init,
        )
        self._pool_broken = False
        logger.warning("[SyncTaskExecutor] Process pool rebuilt")

    def _cleanup_task_metadata(self, task_id: int) -> None:
        self._futures.pop(task_id, None)
        self._submit_times.pop(task_id, None)
        self._task_drivers.pop(task_id, None)
        self._task_types.pop(task_id, None)

    def _kill_stale_worker(
        self,
        task_id: int,
        driver: str,
        elapsed: float,
        refund: bool = True,
    ) -> Optional[SyncTaskResult]:
        """卡死超时任务的处理：标记 broken + 立即整池重建。

        旧实现经 multiprocessing.Manager 共享的 worker_pids 按 pid 精确单杀
        worker；Manager 服务进程是单点，死亡后所有任务在 worker unpickle 参数
        阶段即崩（2026-09-12 20:43 事故），已去除该依赖。stale 场景改为
        立即整池重建：_reclaim_workers_locked 终止全部旧 worker（含卡死任务
        所在 worker，SIGTERM→SIGKILL 最坏 ~2s），池内其他在跑任务以
        BrokenProcessPool 终态走退款路径——与原单杀路径同语义，
        且不再有"单杀失败保留 future"的悬挂分支。
        """
        ai_tool_type = self._task_types.get(task_id)
        logger.error(
            "[SyncTaskExecutor] Stale sync task task_id=%s driver=%s elapsed=%.0fs refund=%s",
            task_id,
            driver,
            elapsed,
            refund,
        )
        self._pool_broken = True
        if self._running and self._executor is not None:
            self._rebuild_pool_locked()

        if not refund:
            # 无失败结果可写终态，直接清理避免元数据泄漏
            self._cleanup_task_metadata(task_id)
            return None
        # refund=True：清理时机由调用方在终态落库后执行
        # （check_results/force_release_task → _handle_result_then_cleanup），
        # 避免「内存已删 + DB 仍 PROCESSING」的孤儿误判窗口
        return SyncTaskResult(
            task_id=task_id,
            ai_tool_type=ai_tool_type or 0,
            success=False,
            error=f"stale timeout after {elapsed:.0f}s",
            error_type="SYSTEM",
        )

    def force_release_task(self, task_id: int, refund: bool = False) -> bool:
        result = None
        with self._state_lock:
            if task_id not in self._futures:
                return False
            driver = self._task_drivers.get(task_id, "unknown")
            submitted_at = self._submit_times.get(task_id)
            elapsed = time.time() - submitted_at if submitted_at else -1
            result = self._kill_stale_worker(task_id, driver, elapsed, refund=refund)
        if result is None:
            with self._state_lock:
                return task_id not in self._futures
        # 先写终态再清理（顺序约束见 _handle_result_then_cleanup）
        self._handle_result_then_cleanup(result)
        return True

    def _purge_dead_workers_locked(self) -> None:
        """清理已死亡的池 worker（须持 _state_lock 调用）。

        Python 3.10 的 ProcessPoolExecutor 不会回收死亡 worker 的名额：
        submit 只按 len(_processes) < max_workers 补 fork。initializer 看门狗
        自杀（或其他原因退出）的 worker 若不清理，池容量会永久缩水、任务
        逐渐堆积。清理后若一个活 worker 都不剩，设 _pool_broken 走既有
        _rebuild_pool_locked 全量重建（rebuild 会取消队列任务，不能轻动）。
        """
        executor = self._executor
        if executor is None:
            return
        processes = getattr(executor, "_processes", None)
        if not processes:
            return
        dead_pids = []
        for pid, proc in list(processes.items()):
            try:
                alive = proc.is_alive()
            except Exception:
                # 状态未知时保守视为存活，避免误触发全量重建
                alive = True
            if not alive:
                dead_pids.append(pid)
        for pid in dead_pids:
            processes.pop(pid, None)
        if dead_pids:
            logger.warning(
                "[SyncTaskExecutor] Purged %d dead pool worker(s): %s",
                len(dead_pids),
                dead_pids,
            )
            if not processes:
                self._pool_broken = True

    def _reclaim_workers_locked(self, processes) -> int:
        """显式终止并回收进程池的全部 worker（须持 _state_lock 调用）。

        ProcessPoolExecutor.shutdown 依赖池管理线程通知 worker 退出；池一旦
        broken（BrokenProcessPool / stale 强杀），卡死在废弃 call queue 上的
        worker 永远收不到退出通知，管理线程自身也随之无法结束，executor 对象
        无法被 GC——旧池的队列管道在父进程永久泄漏，且后续每次 fork 新 worker
        都会完整继承这些 FD（2026-09-12 事故：一天重建 46 次，累积 360 个卡死
        worker、996 根管道，打满 1024 FD 上限后全进程 EMFILE 崩溃）。

        Args:
            processes: shutdown **之前**快照的 [(pid, Process)]。CPython 的
                shutdown() 无条件把 executor._processes 置 None，必须先握住
                Process 对象再关池，否则此处拿到空引用、回收变空操作。

        回收为并行两段式（两段 join 均共享 deadline，持锁最坏 ≈ grace+join
        ≈ 2s，与 worker 数量无关；卡死 worker 对 SIGTERM 走内核默认处置即刻
        退出，通常整体 <1s）：全员 SIGTERM → 共享宽限 deadline 逐个 join →
        顽固者 SIGKILL → join。用 Process 对象的 join（waitpid）收尸而非
        os.kill(pid,0) 轮询探活——后者对"已死未收尸"的僵尸误判为存活，
        会白等整个宽限期。

        权衡：被终止 worker 上仍在运行的任务以 BrokenProcessPool 终态落库退款
        （与 stale 超时强杀同一路径），不会留下 PROCESSING 孤儿。

        Returns:
            实际终止的存活 worker 数（已死亡 worker 仅收尸，不计数）
        """
        if not processes:
            return 0
        dead = []
        alive = []
        for _pid, proc in processes:
            try:
                (alive if proc.is_alive() else dead).append(proc)
            except Exception:
                # 状态未知保守视为存活，宁可多终止一次
                alive.append(proc)

        # 1) 全员 SIGTERM（Windows 上 terminate 即硬杀）
        for proc in alive:
            try:
                proc.terminate()
            except Exception:
                pass

        # 2) 共享宽限 deadline：卡死 worker 对 SIGTERM 走内核默认处置即刻退出，
        #    通常全部 join 在远小于 grace 内返回；deadline 保证最坏总时长有界
        deadline = time.monotonic() + SYNC_WORKER_RECLAIM_GRACE_SECONDS
        stubborn = []
        for proc in alive:
            try:
                proc.join(timeout=max(0.0, deadline - time.monotonic()))
            except Exception:
                pass
            try:
                if proc.is_alive():
                    stubborn.append(proc)
            except Exception:
                stubborn.append(proc)

        # 3) 顽固者 SIGKILL 兜底（join 同样共享 deadline：串行每人 join_timeout
        #    会在全员顽固时把持锁时间放大到 workers×join_timeout）
        for proc in stubborn:
            try:
                proc.kill()
            except Exception:
                pass
        kill_deadline = time.monotonic() + SYNC_WORKER_RECLAIM_JOIN_TIMEOUT
        for proc in stubborn:
            try:
                proc.join(timeout=max(0.0, kill_deadline - time.monotonic()))
            except Exception:
                pass

        # 4) 已死 worker 防御性收尸（is_alive 的 waitpid 通常已 reap，此步兜底）
        reap_deadline = time.monotonic() + SYNC_WORKER_RECLAIM_JOIN_TIMEOUT
        for proc in dead:
            try:
                proc.join(timeout=max(0.0, reap_deadline - time.monotonic()))
            except Exception:
                pass

        return len(alive)

    def submit(self, task_id: int, ai_tool_type: int, implementation_name: str = None) -> bool:
        """
        提交同步任务到进程池

        Args:
            task_id: AI工具ID
            ai_tool_type: AI工具类型
            implementation_name: 实现方名称（可选）

        Returns:
            bool: 是否提交成功
        """
        with self._state_lock:
            if self._running:
                # 先清理死亡 worker，保证下方补 fork / rebuild 判断基于活进程数
                self._purge_dead_workers_locked()

            if self._pool_broken and self._running:
                self._rebuild_pool_locked()

            if not self.is_running():
                logger.error("[SyncTaskExecutor] Executor not running")
                return False

            if task_id in self._futures:
                logger.warning(f"[SyncTaskExecutor] Task {task_id} already submitted")
                return False

            try:
                future = self._executor.submit(_execute_sync_task, task_id, ai_tool_type)
                self._futures[task_id] = future
                self._submit_times[task_id] = time.time()
                self._task_drivers[task_id] = implementation_name or "unknown"
                self._task_types[task_id] = ai_tool_type
                logger.info(
                    "[SyncTaskExecutor] Submitted task %s implementation=%s",
                    task_id,
                    implementation_name,
                )
                return True
            except BrokenProcessPool as e:
                self._pool_broken = True
                logger.error(f"[SyncTaskExecutor] Process pool broken while submitting task {task_id}: {e}")
                return False
            except Exception as e:
                logger.error(f"[SyncTaskExecutor] Failed to submit task {task_id}: {e}")
                return False

    def check_results(self) -> None:
        """
        检查已完成任务的结果并处理
        """
        failure_results = []

        with self._state_lock:
            if not self._futures:
                return

            now = time.time()
            stale_detection_enabled = self._is_stale_detection_enabled()

            for task_id, future in list(self._futures.items()):
                if not future.done():
                    if not stale_detection_enabled:
                        continue
                    driver = self._task_drivers.get(task_id, "unknown")
                    stale_timeout = get_sync_task_stale_timeout(driver)
                    submitted_at = self._submit_times.get(task_id, now)
                    elapsed = now - submitted_at
                    if stale_timeout is not None and elapsed >= stale_timeout:
                        result = self._kill_stale_worker(task_id, driver, elapsed, refund=True)
                        if result:
                            failure_results.append(result)
                    continue

                try:
                    result = future.result(timeout=0)
                    failure_results.append(result)
                except BrokenProcessPool as e:
                    self._pool_broken = True
                    logger.error(f"[SyncTaskExecutor] BrokenProcessPool while reading task {task_id}: {e}")
                    result = SyncTaskResult(
                        task_id=task_id,
                        ai_tool_type=self._task_types.get(task_id, 0),
                        success=False,
                        error=str(e),
                        error_type="SYSTEM",
                    )
                    failure_results.append(result)
                except Exception as e:
                    logger.error(f"[SyncTaskExecutor] Task {task_id} raised exception: {e}")
                    result = SyncTaskResult(
                        task_id=task_id,
                        ai_tool_type=self._task_types.get(task_id, 0),
                        success=False,
                        error=str(e),
                        error_type="SYSTEM",
                    )
                    failure_results.append(result)
                    continue

        # ⚠️ 终态落库后才允许清理 _futures（见 _handle_result_then_cleanup 注释），
        # 此处禁止在锁内批量 pop：那会重新打开孤儿误判窗口。
        for result in failure_results:
            self._handle_result_then_cleanup(result)

    def _handle_result_then_cleanup(self, result: SyncTaskResult) -> None:
        """
        先写任务终态（_safe_handle_task_result 落库 COMPLETED/FAILED），
        再清理 _futures 等内存元数据。

        ⚠️ 顺序不可颠倒：终态落库前 task_id 必须保留在 _futures 中（is_task_running()
        返回 True），否则调度器（visual_task._check_task_status 的孤儿恢复）会在
        「内存已删 + DB 仍 PROCESSING」的窗口内把刚完成的任务误判为子进程崩溃，
        重置 PENDING 重新提交，造成同供应商重复计费调用。
        """
        try:
            self._safe_handle_task_result(result)
        finally:
            with self._state_lock:
                self._cleanup_task_metadata(result.task_id)

    def _safe_handle_task_result(self, result: SyncTaskResult) -> None:
        handling_error = None
        try:
            self._handle_task_result(result)
            return
        except Exception as exc:
            handling_error = exc
            logger.error(
                "[SyncTaskExecutor] Failed to handle result for task %s: %s",
                result.task_id,
                exc,
                exc_info=True,
            )

        try:
            self._handle_task_failure(
                result.task_id,
                str(handling_error),
                "SYSTEM",
                result.ai_tool_type,
            )
        except Exception as fallback_exc:
            logger.critical(
                "[SyncTaskExecutor] CRITICAL: fallback failure handling failed for task %s: %s",
                result.task_id,
                fallback_exc,
                exc_info=True,
            )

    def _handle_task_result(self, result: SyncTaskResult) -> None:
        """
        处理任务结果

        Args:
            result: 任务执行结果
        """
        from model import AIToolsModel, TasksModel
        from config.constant import (
            AI_TOOL_STATUS_COMPLETED,
            TASK_STATUS_COMPLETED,
        )

        task_id = result.task_id

        if result.success:
            # 任务成功
            AIToolsModel.update_with_cdn_sync(
                task_id,
                result_url=result.result_url,
                status=AI_TOOL_STATUS_COMPLETED,
                completed_time=datetime.now()
            )
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_COMPLETED)

            # 标记当前实现方尝试为成功
            try:
                from model.implementation_attempts import ImplementationAttemptModel, ATTEMPT_STATUS_SUCCESS
                ImplementationAttemptModel.mark_active_attempt_completed(task_id, ATTEMPT_STATUS_SUCCESS)
            except Exception as e:
                logger.warning(f"[SyncTaskExecutor] Failed to mark attempt as success for task {task_id}: {e}")

            # 供应商切换差价结算（多扣退差/少扣补收，幂等；本回调运行于进程池 worker，直接同步调用）
            try:
                from utils.computing_power import settle_success_diff_for_task
                settle_success_diff_for_task(task_id)
            except Exception as e:
                logger.warning(f"[SyncTaskExecutor] Settle diff failed for task {task_id}: {e}")

            logger.info(f"[SyncTaskExecutor] Task {task_id} completed successfully")
        else:
            # 任务失败
            self._handle_task_failure(task_id, result.error, result.error_type, result.ai_tool_type)

    def _handle_task_failure(self, task_id: int, error: str, error_type: str = "SYSTEM", ai_tool_type: int = None) -> None:
        """
        处理任务失败 - 委托给 visual_task 的统一失败处理（尝试 before_finish 重试）

        无论是 USER 错误还是 SYSTEM 错误，都尝试重试，
        因为不同供应商的审核策略、网络状况、API 行为都不同。

        Args:
            task_id: 任务ID
            error: 错误信息
            error_type: 错误类型 (USER/SYSTEM)
            ai_tool_type: AI工具类型
        """
        from model import AIToolsModel, TasksModel
        from config.constant import AI_TOOL_STATUS_FAILED, TASK_STATUS_FAILED

        # 委托给 visual_task 的统一失败处理（尝试 before_finish 重试）
        try:
            ai_tool = AIToolsModel.get_by_id(task_id)
            if ai_tool:
                from task.visual_task import _handle_task_failure as unified_failure
                unified_failure(
                    task_id=task_id,
                    ai_tool_type=ai_tool_type or ai_tool.type,
                    reason=error,
                    user_id=ai_tool.user_id
                )
                logger.info(f"[SyncTaskExecutor] Task {task_id} delegated to unified failure handler")
                return
        except Exception as e:
            logger.error(f"[SyncTaskExecutor] Unified handler failed for task {task_id}: {e}")

        # 兜底：直接标记失败
        AIToolsModel.update(task_id, status=AI_TOOL_STATUS_FAILED, message=error, completed_time=datetime.now())
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)

        try:
            ai_tool = AIToolsModel.get_by_id(task_id)
            if ai_tool:
                from task.visual_task import _refund_computing_power
                _refund_computing_power(ai_tool, error)
        except Exception as e:
            logger.error(f"[SyncTaskExecutor] Failed to refund for task {task_id}: {e}")

        logger.info(f"[SyncTaskExecutor] Task {task_id} marked as failed: {error}")

    def get_pending_count(self) -> int:
        """Return the number of tracked futures."""
        return len(self._futures)

    def get_metrics(self) -> Dict[str, Any]:
        oldest_submit_age = 0
        if self._submit_times:
            oldest_submit_age = time.time() - min(self._submit_times.values())
        return {
            "running": self.is_running(),
            "pending_count": len(self._futures),
            "pool_broken": self._pool_broken,
            "oldest_submit_age": oldest_submit_age,
            "worker_pids": sorted(
                (getattr(self._executor, "_processes", None) or {}).keys()
            ),
        }


def process_sync_task_results():
    """Process completed sync task results."""
    executor = SyncTaskExecutor.get_instance()
    if executor.is_running():
        executor.check_results()


# 单例获取方法
def get_sync_task_executor() -> SyncTaskExecutor:
    """Return the singleton sync task executor."""
    return SyncTaskExecutor.get_instance()


# 扩展 SyncTaskExecutor 类添加 get_instance 方法
SyncTaskExecutor.get_instance = staticmethod(lambda: SyncTaskExecutor())
