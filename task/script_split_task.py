"""
Script split task worker - 单步状态机消费者。

见 docs/script/script_parser_incremental_split_design.md §12。
注册到 task/scheduler.py 的 IntervalTrigger，每个 tick：
1. claim_next_task 原子领取一个任务（worker_id/lease_until）。
2. 只推进一个有限步骤（plan / generate_segment / publish）。
3. 步骤完成后立即释放租约，下一次 tick 再推进。

这样避免一个 job 连续占用数十分钟，让取消/暂停/进度查询能在段间及时生效，
也让调度器进程崩溃后其他进程在租约过期后从第一个未完成段继续。
"""
import asyncio
import logging
from functools import partial

from config.constant import ScriptSplitConstants
from model.script_split_task import ScriptSplitTaskModel
from services import script_split_engine as engine

logger = logging.getLogger(__name__)


async def process_script_split_tasks() -> None:
    """单次 tick：领取并推进一个任务的一个步骤。"""
    task = ScriptSplitTaskModel.claim_next_task(
        ScriptSplitConstants.TASK_LEASE_SECONDS
    )
    if task is None:
        return

    try:
        # 看门狗：整个单步包 wall-clock 超时，防止底层 LLM HTTP 调用永久阻塞
        # 导致 max_instances=1 的调度 job 被独占（历史 bug：一次 DeepSeek 请求
        # 卡死让后续 1 小时的 tick 全部被 APScheduler 丢弃）。
        # 超时后底层 to_thread 线程无法强杀（Python 限制），会继续在后台跑，
        # 但 job 函数能返回，APScheduler 可调度下一 tick。
        try:
            await asyncio.wait_for(
                _advance_one_step(task),
                timeout=ScriptSplitConstants.WORKER_STEP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error(
                "task %s 单步超过 %ds 看门狗上限，释放租约并暂停任务",
                task.id, ScriptSplitConstants.WORKER_STEP_TIMEOUT_SECONDS,
            )
            ScriptSplitTaskModel.update_status(
                task.id, ScriptSplitConstants.STATUS_PAUSED,
                last_error_code="step_watchdog_timeout",
                last_error_message=(
                    f"本次调度步骤超过 {ScriptSplitConstants.WORKER_STEP_TIMEOUT_SECONDS}s，"
                    f"已暂停并保留检查点，可点击继续重试。"
                ),
            )
            ScriptSplitTaskModel.release_lease(task.id)
            return
        # 正常完成单步：释放租约，等待下一 tick
        ScriptSplitTaskModel.release_lease(task.id)
    except engine.CancelledByUser:
        _transition_to_cancelled(task.id)
    except engine.WaitingAuth:
        ScriptSplitTaskModel.update_status(
            task.id, ScriptSplitConstants.STATUS_WAITING_AUTH,
            last_error_code="waiting_auth",
            last_error_message="鉴权失效，请刷新页面后继续",
        )
        ScriptSplitTaskModel.release_lease(task.id)
        logger.info("task %s 进入 waiting_auth", task.id)
    except engine.TaskPaused as e:
        ScriptSplitTaskModel.update_status(
            task.id, ScriptSplitConstants.STATUS_PAUSED,
            last_error_code=e.code,
            last_error_message=e.message,
        )
        ScriptSplitTaskModel.release_lease(task.id)
        logger.warning("task %s 进入 paused: %s", task.id, e.message)
    except engine.EngineError as e:
        terminal_codes = {
            "invalid_segment_checkpoint_state",
            "invalid_task_state",
            "empty_script",
        }
        target_status = (
            ScriptSplitConstants.STATUS_FAILED
            if e.code in terminal_codes
            else ScriptSplitConstants.STATUS_PAUSED
        )
        ScriptSplitTaskModel.update_status(
            task.id, target_status,
            last_error_code=e.code,
            last_error_message=e.message,
        )
        ScriptSplitTaskModel.release_lease(task.id)
        logger.warning("task %s 单步失败并进入 %s [%s]: %s",
                       task.id, target_status, e.code, e.message)
    except Exception as e:
        # 未知异常：标记 failed，释放租约
        logger.exception("task %s 单步未知异常", task.id)
        ScriptSplitTaskModel.update_status(
            task.id, ScriptSplitConstants.STATUS_FAILED,
            last_error_code="unknown_error",
            last_error_message=str(e),
        )
        ScriptSplitTaskModel.release_lease(task.id)


async def _advance_one_step(task) -> None:
    """根据任务当前状态决定执行哪个单步。

    状态机：
      queued / planning(初始)  → step_plan
      generating               → step_generate_segment（内部判断是否全部完成）
      publishing               → step_publish → completed
    """
    status = task.status

    if status == ScriptSplitConstants.STATUS_CANCELLING:
        # cancel 接口可能在任务没有持有租约时提交请求。claim_next_task 会在
        # 下一个 tick 领取 cancelling；必须显式抛出取消信号，交给外层统一
        # 写入 cancelled 并释放租约，不能把它当成未知状态反复跳过。
        raise engine.CancelledByUser()

    if status == ScriptSplitConstants.STATUS_QUEUED:
        ScriptSplitTaskModel.update_status(
            task.id, ScriptSplitConstants.STATUS_PLANNING,
            phase="planning", progress=5,
        )
        await engine.step_plan(task)
        return

    if status == ScriptSplitConstants.STATUS_PLANNING:
        await engine.step_plan(task)
        return

    if status == ScriptSplitConstants.STATUS_GENERATING:
        await engine.step_generate_segment(task)
        return

    if status == ScriptSplitConstants.STATUS_PUBLISHING:
        # 发布：step_publish 内部标记 completed 或抛错
        await engine.step_publish(task)
        return

    if status in {
        ScriptSplitConstants.STATUS_MERGING,
        ScriptSplitConstants.STATUS_VALIDATING,
    }:
        raise engine.EngineError(
            "invalid_task_state",
            f"新状态机不再执行旧状态 {status}",
        )

    # 已终态或无法识别的状态：释放租约，不推进
    logger.info("task %s 状态 %s 无可执行步骤，跳过", task.id, status)


def _transition_to_cancelled(task_id: int) -> None:
    """取消生效：丢弃当前响应，进入 cancelled 终态。"""
    ScriptSplitTaskModel.update_status(
        task_id, ScriptSplitConstants.STATUS_CANCELLED,
        phase="cancelled",
    )
    ScriptSplitTaskModel.release_lease(task_id)
    logger.info("task %s 已取消", task_id)


def make_scheduler_job():
    """构造可注册到 scheduler.add_job 的可调用对象。

    用法（在 task/scheduler.py:init_scheduler 内）::

        from task.script_split_task import make_scheduler_job
        scheduler.add_job(
            make_scheduler_job(),
            IntervalTrigger(seconds=ScriptSplitConstants.SCHEDULER_INTERVAL_SECONDS),
            id='process_script_split_tasks',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    """
    from task.scheduler import _run_async_task
    return partial(_run_async_task, process_script_split_tasks)


__all__ = [
    "process_script_split_tasks",
    "make_scheduler_job",
]
