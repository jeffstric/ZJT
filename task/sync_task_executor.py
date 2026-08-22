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
from multiprocessing import Manager

from config.constant import get_sync_task_stale_timeout

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SyncTaskResult:
    """Result returned by a sync task worker."""
    task_id: int
    ai_tool_type: int
    success: bool
    result_url: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None



def _enterprise_sync_worker_init() -> None:
    """ProcessPool 子进程 initializer：注入商业 Provider + 许可证 runtime。

    子进程不继承父进程的 register_provider / _manager 等模块全局状态。
    未初始化时 face_mask 会静默走社区 skip，多密钥池也会退化为单密钥。
    """
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


def _execute_sync_task(task_id: int, ai_tool_type: int, worker_pids=None) -> SyncTaskResult:
    """
    子进程入口函数 - 执行同步任务

    ⚠️ 关键设计：此函数运行在独立子进程中（ProcessPoolExecutor），不能引用主进程的
    数据库连接、锁、或任何可变全局状态。每次调用都需要重新导入模块和初始化连接。

    Args:
        task_id: AI工具ID
        ai_tool_type: AI工具类型
        worker_pids: 工作进程PID字典（可选）

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

    logger.info(f"[SyncTask] Starting task {task_id} (type: {ai_tool_type})")
    if worker_pids is not None:
        try:
            worker_pids[task_id] = os.getpid()
        except Exception as exc:
            logger.warning(f"[SyncTask] Failed to record worker pid for task {task_id}: {exc}")

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
        self._manager = None
        self._worker_pids: Dict[int, int] = {}
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
            self._manager = Manager()
            self._worker_pids = self._manager.dict()
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
            self._executor.shutdown(wait=wait)
            self._executor = None

        self._futures.clear()
        self._submit_times.clear()
        self._task_drivers.clear()
        self._task_types.clear()
        self._worker_pids.clear()
        if self._manager:
            try:
                self._manager.shutdown()
            except Exception as exc:
                logger.warning(f"[SyncTaskExecutor] Failed to shutdown manager: {exc}")
            self._manager = None
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
            try:
                old_executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                old_executor.shutdown(wait=False)
            except Exception as exc:
                logger.warning(f"[SyncTaskExecutor] Error shutting down broken pool: {exc}")

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
        self._worker_pids.pop(task_id, None)

    def _terminate_worker_for_task(self, task_id: int) -> bool:
        pid = self._worker_pids.get(task_id)
        if not pid:
            return False
        try:
            from utils.process_utils import terminate_worker_process

            return terminate_worker_process(pid, grace_seconds=2.0)
        except Exception as exc:
            logger.error(f"[SyncTaskExecutor] Failed to terminate worker pid={pid} task={task_id}: {exc}")
            return False

    def _kill_stale_worker(
        self,
        task_id: int,
        driver: str,
        elapsed: float,
        refund: bool = True,
    ) -> Optional[SyncTaskResult]:
        ai_tool_type = self._task_types.get(task_id)
        logger.error(
            "[SyncTaskExecutor] Killing stale sync task task_id=%s driver=%s elapsed=%.0fs refund=%s",
            task_id,
            driver,
            elapsed,
            refund,
        )
        future = self._futures.get(task_id)
        terminated = self._terminate_worker_for_task(task_id)
        cancelled = False
        if future is not None:
            try:
                cancelled = future.cancel()
            except Exception as exc:
                logger.warning("[SyncTaskExecutor] Failed to cancel stale future task_id=%s: %s", task_id, exc)

        if not terminated and not cancelled:
            logger.error(
                "[SyncTaskExecutor] Stale task task_id=%s was not released; keep future for next check",
                task_id,
            )
            return None

        self._cleanup_task_metadata(task_id)
        if terminated:
            self._pool_broken = True

        if not refund:
            return None
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
            released = task_id not in self._futures
        if result:
            self._safe_handle_task_result(result)
        return released

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
            if self._pool_broken and self._running:
                self._rebuild_pool_locked()

            if not self.is_running():
                logger.error("[SyncTaskExecutor] Executor not running")
                return False

            if task_id in self._futures:
                logger.warning(f"[SyncTaskExecutor] Task {task_id} already submitted")
                return False

            try:
                future = self._executor.submit(_execute_sync_task, task_id, ai_tool_type, self._worker_pids)
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

            completed_task_ids = []
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

                completed_task_ids.append(task_id)
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

            # 清理已完成的future
            for task_id in completed_task_ids:
                self._cleanup_task_metadata(task_id)

        for result in failure_results:
            self._safe_handle_task_result(result)

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
            "worker_pids": dict(self._worker_pids),
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
