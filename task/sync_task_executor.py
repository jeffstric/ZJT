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
from concurrent.futures import ProcessPoolExecutor, Future
from dataclasses import dataclass
from typing import Dict, Optional, Any
from multiprocessing import Manager

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SyncTaskResult:
    """同步任务结果"""
    task_id: int
    ai_tool_type: int
    success: bool
    result_url: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None


def _execute_sync_task(task_id: int, ai_tool_type: int) -> SyncTaskResult:
    """
    子进程入口函数 - 执行同步任务

    Args:
        task_id: AI工具ID
        ai_tool_type: AI工具类型

    Returns:
        SyncTaskResult: 任务执行结果
    """
    # 子进程需要重新初始化数据库连接等
    # 这里通过重新导入来实现
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

    try:
        # 更新状态为处理中
        AIToolsModel.update(task_id, status=AI_TOOL_STATUS_PROCESSING)
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_PROCESSING)

        # 获取AI工具详情
        ai_tool = AIToolsModel.get_by_id(task_id)
        if not ai_tool:
            logger.error(f"[SyncTask] Task {task_id} not found in database")
            return SyncTaskResult(
                task_id=task_id,
                ai_tool_type=ai_tool_type,
                success=False,
                error="任务不存在",
                error_type="SYSTEM"
            )

        # 调用驱动提交任务（同步执行）
        from task.visual_drivers import VideoDriverFactory

        driver = VideoDriverFactory.create_driver_by_type(ai_tool_type)
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
            error = result.get("error", "未知错误")
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

            # 判断是否已经是本地路径
            is_local_path = result_url and result_url.startswith("/upload/")

            if not is_local_path and result_url:
                # 下载并缓存媒体文件
                from utils.media_cache import download_and_cache

                # 判断媒体类型
                media_type = "video"
                ext = result_url.split('?')[0].split('.')[-1].lower()
                if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    media_type = "image"

                # 下载并缓存
                cached_url = asyncio.run(download_and_cache(result_url, task_id, media_type))
                result_url = cached_url if cached_url else result_url

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
            error="异步模式任务不应提交到同步执行器",
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
        self._running = False

        # 配置参数
        self._max_workers = self._get_max_workers()
        self._check_interval = self._get_check_interval()

    def _get_max_workers(self) -> int:
        """获取进程池最大并发数"""
        try:
            from config.config_util import get_dynamic_config_value
            return get_dynamic_config_value("sync_task", "max_workers", default=4)
        except Exception:
            return 4

    def _get_check_interval(self) -> int:
        """获取结果检查间隔（秒）"""
        try:
            from config.config_util import get_dynamic_config_value
            return get_dynamic_config_value("sync_task", "check_interval", default=5)
        except Exception:
            return 5

    def start(self) -> bool:
        """
        启动同步任务执行器

        Returns:
            bool: 是否启动成功
        """
        if self._running:
            logger.warning("[SyncTaskExecutor] Already running")
            return True

        try:
            self._executor = ProcessPoolExecutor(max_workers=self._max_workers)
            self._running = True
            logger.info(f"[SyncTaskExecutor] Started with max_workers={self._max_workers}")
            return True
        except Exception as e:
            logger.error(f"[SyncTaskExecutor] Failed to start: {e}")
            return False

    def shutdown(self, wait: bool = True) -> None:
        """
        关闭同步任务执行器

        Args:
            wait: 是否等待所有任务完成
        """
        if not self._running:
            return

        self._running = False

        if self._executor:
            self._executor.shutdown(wait=wait)
            self._executor = None

        self._futures.clear()
        logger.info("[SyncTaskExecutor] Shutdown complete")

    def is_running(self) -> bool:
        """检查执行器是否运行中"""
        return self._running and self._executor is not None

    def submit(self, task_id: int, ai_tool_type: int) -> bool:
        """
        提交同步任务到进程池

        Args:
            task_id: AI工具ID
            ai_tool_type: AI工具类型

        Returns:
            bool: 是否提交成功
        """
        if not self.is_running():
            logger.error("[SyncTaskExecutor] Executor not running")
            return False

        if task_id in self._futures:
            logger.warning(f"[SyncTaskExecutor] Task {task_id} already submitted")
            return False

        try:
            future = self._executor.submit(_execute_sync_task, task_id, ai_tool_type)
            self._futures[task_id] = future
            logger.info(f"[SyncTaskExecutor] Submitted task {task_id}")
            return True
        except Exception as e:
            logger.error(f"[SyncTaskExecutor] Failed to submit task {task_id}: {e}")
            return False

    def check_results(self) -> None:
        """
        检查已完成任务的结果并处理
        """
        if not self._futures:
            return

        completed_task_ids = []

        for task_id, future in self._futures.items():
            if future.done():
                completed_task_ids.append(task_id)
                try:
                    result = future.result()
                    self._handle_task_result(result)
                except Exception as e:
                    logger.error(f"[SyncTaskExecutor] Task {task_id} raised exception: {e}")
                    self._handle_task_failure(task_id, str(e))

        # 清理已完成的future
        for task_id in completed_task_ids:
            del self._futures[task_id]

    def _handle_task_result(self, result: SyncTaskResult) -> None:
        """
        处理任务结果

        Args:
            result: 任务执行结果
        """
        from model import AIToolsModel, TasksModel
        from config.constant import (
            AI_TOOL_STATUS_COMPLETED,
            AI_TOOL_STATUS_FAILED,
            TASK_STATUS_COMPLETED,
            TASK_STATUS_FAILED,
        )

        task_id = result.task_id

        if result.success:
            # 任务成功
            AIToolsModel.update(
                task_id,
                result_url=result.result_url,
                status=AI_TOOL_STATUS_COMPLETED
            )
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_COMPLETED)
            logger.info(f"[SyncTaskExecutor] Task {task_id} completed successfully")
        else:
            # 任务失败
            self._handle_task_failure(task_id, result.error, result.error_type)

    def _handle_task_failure(self, task_id: int, error: str, error_type: str = "SYSTEM") -> None:
        """
        处理任务失败 - 直接标记失败并退还算力

        Args:
            task_id: 任务ID
            error: 错误信息
            error_type: 错误类型
        """
        from model import AIToolsModel, TasksModel
        from config.constant import (
            AI_TOOL_STATUS_FAILED,
            TASK_STATUS_FAILED,
        )

        # 更新任务状态
        AIToolsModel.update(task_id, status=AI_TOOL_STATUS_FAILED, message=error)
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)

        # 退还算力
        try:
            ai_tool = AIToolsModel.get_by_id(task_id)
            if ai_tool:
                from task.visual_task import _refund_computing_power
                _refund_computing_power(ai_tool, error)
        except Exception as e:
            logger.error(f"[SyncTaskExecutor] Failed to refund computing power for task {task_id}: {e}")

        logger.info(f"[SyncTaskExecutor] Task {task_id} marked as failed: {error}")

    def get_pending_count(self) -> int:
        """获取待处理任务数量"""
        return len(self._futures)


def process_sync_task_results():
    """
    处理已完成的同步任务结果 - 供调度器调用
    """
    executor = SyncTaskExecutor.get_instance()
    if executor.is_running():
        executor.check_results()


# 单例获取方法
def get_sync_task_executor() -> SyncTaskExecutor:
    """获取同步任务执行器单例"""
    return SyncTaskExecutor.get_instance()


# 扩展 SyncTaskExecutor 类添加 get_instance 方法
SyncTaskExecutor.get_instance = staticmethod(lambda: SyncTaskExecutor())
