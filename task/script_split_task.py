"""
Script split task worker - 单步状态机消费者。

见 docs/script/script_parser_incremental_split_design.md §12。
注册到 task/scheduler.py 的 IntervalTrigger，每个 tick：
1. claim_next_task 原子领取任务并写入每次领取唯一的 worker_id。
2. 启动续租守护，并集中回收上次崩溃遗留的 generating 段。
3. 只推进一个有限步骤（plan / generate_segment / publish）。
4. 步骤完成后按 worker_id 条件释放租约，下一次 tick 再推进。

这样避免一个 job 连续占用数十分钟，让取消/暂停/进度查询能在段间及时生效，
也让调度器进程崩溃后其他进程在租约过期后从第一个未完成段继续。
"""
import asyncio
import logging
from functools import partial

from config.constant import ScriptSplitConstants
from model.script_split_segment import ScriptSplitSegmentModel
from model.script_split_task import ScriptSplitTaskModel
from services import script_split_engine as engine
from utils.sentry_util import SentryUtil

logger = logging.getLogger(__name__)


def _record_gather_exceptions(results, context: str) -> None:
    """Log + Sentry each exception returned by gather(return_exceptions=True)."""
    for item in results or ():
        if isinstance(item, BaseException) and not isinstance(item, asyncio.CancelledError):
            try:
                logger.error(
                    "%s gather exception: %s",
                    context,
                    item,
                    exc_info=(type(item), item, item.__traceback__),
                )
                SentryUtil.capture_exception(item)
            except Exception:
                logger.exception("%s failed to record gather exception", context)


class LeaseLostError(RuntimeError):
    """当前步骤已不再持有 claim 租约，禁止继续写任务状态。"""


async def _lease_heartbeat(
    task_id: int,
    worker_id: str,
    stop_event: asyncio.Event,
) -> None:
    """周期续租；续租失败即通知编排层取消当前步骤。"""
    interval = float(ScriptSplitConstants.LEASE_RENEW_INTERVAL_SECONDS)
    lease_seconds = int(ScriptSplitConstants.TASK_LEASE_SECONDS)
    db_timeout = float(ScriptSplitConstants.LEASE_RENEW_DB_TIMEOUT_SECONDS)
    if interval <= 0 or interval > lease_seconds / 3:
        raise LeaseLostError(
            f"invalid lease renew interval: {interval}s for lease {lease_seconds}s"
        )
    if db_timeout <= 0 or db_timeout >= interval:
        raise LeaseLostError(
            f"invalid lease renew db timeout: {db_timeout}s for interval {interval}s"
        )

    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        try:
            renewed = await asyncio.wait_for(
                asyncio.to_thread(
                    ScriptSplitTaskModel.renew_lease,
                    task_id,
                    worker_id,
                    lease_seconds,
                ),
                timeout=db_timeout,
            )
        except Exception as exc:
            raise LeaseLostError(f"task {task_id} lease renew failed: {exc}") from exc
        if not renewed:
            raise LeaseLostError(f"task {task_id} lease owner changed")


async def _advance_claimed_step(task, worker_id: str) -> None:
    recovery = await asyncio.to_thread(
        ScriptSplitSegmentModel.reclaim_stale_generating,
        task.id,
        worker_id,
        ScriptSplitConstants.STALE_SEGMENT_MAX_RECOVERIES,
    )
    if not recovery.get("lease_owned"):
        raise LeaseLostError(f"task {task.id} lease lost before stale recovery")
    reclaimed_count = int(recovery.get("reclaimed_count") or 0)
    if reclaimed_count:
        logger.warning(
            "task %s reclaimed %d stale generating segment(s)",
            task.id,
            reclaimed_count,
        )
    exhausted = recovery.get("exhausted_segment_indexes") or []
    if exhausted:
        indexes = ", ".join(str(index) for index in exhausted)
        raise engine.TaskPaused(
            ScriptSplitConstants.ERROR_SEGMENT_REPEATEDLY_INTERRUPTED,
            f"段 {indexes} 连续生成中断已达到上限 "
            f"{ScriptSplitConstants.STALE_SEGMENT_MAX_RECOVERIES} 次，请检查服务或模型后继续",
        )
    await _advance_one_step(task)


async def _run_with_lease_heartbeat(task, worker_id: str) -> None:
    """并行守护业务步骤和租约；任一续租失败都会取消业务 coroutine。"""
    stop_event = asyncio.Event()
    heartbeat = asyncio.create_task(
        _lease_heartbeat(task.id, worker_id, stop_event),
        name=f"script-split-lease-{task.id}",
    )
    step = asyncio.create_task(
        asyncio.wait_for(
            _advance_claimed_step(task, worker_id),
            timeout=ScriptSplitConstants.WORKER_STEP_TIMEOUT_SECONDS,
        ),
        name=f"script-split-step-{task.id}",
    )
    try:
        done, _ = await asyncio.wait(
            {heartbeat, step},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat in done:
            heartbeat_error = heartbeat.exception()
            if heartbeat_error is not None:
                step.cancel()
                step_results = await asyncio.gather(step, return_exceptions=True)
                _record_gather_exceptions(step_results, "script_split step-cancel")
                raise heartbeat_error
        await step
    finally:
        stop_event.set()
        if not heartbeat.done():
            heartbeat.cancel()
        heartbeat_results = await asyncio.gather(heartbeat, return_exceptions=True)
        _record_gather_exceptions(heartbeat_results, "script_split heartbeat")


async def process_script_split_tasks() -> None:
    """单次 tick：领取并推进一个任务的一个步骤。"""
    task = await asyncio.to_thread(
        ScriptSplitTaskModel.claim_next_task,
        ScriptSplitConstants.TASK_LEASE_SECONDS,
    )
    if task is None:
        return
    worker_id = str(task.worker_id or "")

    try:
        # 看门狗：整个单步包 wall-clock 超时，防止底层 LLM HTTP 调用永久阻塞
        # 导致 max_instances=1 的调度 job 被独占（历史 bug：一次 DeepSeek 请求
        # 卡死让后续 1 小时的 tick 全部被 APScheduler 丢弃）。
        # 超时后底层 to_thread 线程无法强杀（Python 限制），会继续在后台跑，
        # 但 job 函数能返回，APScheduler 可调度下一 tick。
        try:
            if not worker_id:
                raise LeaseLostError(f"task {task.id} claim returned empty worker_id")
            await _run_with_lease_heartbeat(task, worker_id)
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
            return
    except LeaseLostError as exc:
        # 不得覆盖新 owner 的任务状态。finally 仍执行 owner-checked release：
        # 若本 claim 仍是 owner 可立即让下个 tick 回收；owner 已变化则更新 0 行。
        logger.error("task %s 停止执行：%s", task.id, exc)
    except engine.CancelledByUser:
        _transition_to_cancelled(task.id)
    except engine.WaitingAuth:
        ScriptSplitTaskModel.update_status(
            task.id, ScriptSplitConstants.STATUS_WAITING_AUTH,
            last_error_code="waiting_auth",
            last_error_message="鉴权失效，请刷新页面后继续",
        )
        logger.info("task %s 进入 waiting_auth", task.id)
    except engine.TaskPaused as e:
        ScriptSplitTaskModel.update_status(
            task.id, ScriptSplitConstants.STATUS_PAUSED,
            last_error_code=e.code,
            last_error_message=e.message,
        )
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
    finally:
        if worker_id:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        ScriptSplitTaskModel.release_lease,
                        task.id,
                        worker_id,
                    ),
                    timeout=ScriptSplitConstants.LEASE_RENEW_DB_TIMEOUT_SECONDS,
                )
            except Exception:
                logger.exception("task %s owner-checked release lease failed", task.id)


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
    """取消生效：丢弃当前响应，进入 cancelled 终态；租约由外层 finally 释放。"""
    ScriptSplitTaskModel.update_status(
        task_id, ScriptSplitConstants.STATUS_CANCELLED,
        phase="cancelled",
    )
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
