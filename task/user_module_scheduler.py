"""用户模块调度任务注册（由主仓 task/scheduler.py 惰性调用）。

包含任务提交/轮询触发与实现方绑定注册表周期重载；develop_f1214 起随用户
模块子系统常驻主仓（enterprise 旧版并存时由 bootstrap 分流优先使用旧版）。
"""

from __future__ import annotations

import logging

from apscheduler.triggers.interval import IntervalTrigger

from config.constant import (
    USER_MODULE_BINDING_RELOAD_INTERVAL_SECONDS,
    USER_MODULE_SCHEDULER_INTERVAL_SECONDS,
)
from services.user_module_binding_service import load_user_module_bindings
from task.user_module_task import process_user_module_jobs

logger = logging.getLogger(__name__)


def register_user_module_scheduler_jobs(scheduler, run_async_task) -> None:
    """注册用户模块相关的周期任务。

    run_async_task: 把异步协程函数包装为同步调度回调的工厂（主仓 _run_async_task）。
    """
    scheduler.add_job(
        func=run_async_task(process_user_module_jobs),
        trigger=IntervalTrigger(seconds=USER_MODULE_SCHEDULER_INTERVAL_SECONDS),
        id='process_user_module_jobs',
        name='Process user module jobs',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # 实现方绑定注册表重载：web 进程创建/删除绑定即时生效，
    # scheduler 进程经此任务周期感知（最长重载间隔见常量）。
    load_user_module_bindings()
    scheduler.add_job(
        func=load_user_module_bindings,
        trigger=IntervalTrigger(seconds=USER_MODULE_BINDING_RELOAD_INTERVAL_SECONDS),
        id='reload_user_module_bindings',
        name='Reload user module binding registrations',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("用户模块调度任务已注册")


__all__ = ["register_user_module_scheduler_jobs"]
