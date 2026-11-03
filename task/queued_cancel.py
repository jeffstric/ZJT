"""排队任务的延迟取消落账。

预处理步骤已经开工时，取消接口只把 ai_tools.cancel_requested 置 1。
真正改成 CANCELLED 并退款，发生在「下一步不会再调用上游」的检查点：
步骤分发看到标识后放弃 execute，或当前步骤结束后阶段检查不再推进。
退款只在条件更新命中时执行一次。
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def cancel_requested_flag(ai_tool) -> bool:
    """仅真正的整数 1 视为已请求。

    MagicMock 的 int() 在 Python 3.12 会得到 1，不能拿来判断测试桩。
    缺字段、None、布尔值都视为未请求。
    """
    if ai_tool is None:
        return False
    value = getattr(ai_tool, "cancel_requested", 0)
    return type(value) is int and value == 1


def should_defer_cancel(ai_tool, has_processing: bool) -> bool:
    """预处理阶段且（已有步骤在途，或用户已经点过取消）时，不立刻退款。"""
    from config.constant import AI_TOOL_STATUS_WAITING_PARAM_PREPARE

    if ai_tool is None:
        return False
    if getattr(ai_tool, "status", None) != AI_TOOL_STATUS_WAITING_PARAM_PREPARE:
        return False
    return bool(has_processing) or cancel_requested_flag(ai_tool)


def commit_deferred_cancel(ai_tool_id: int) -> bool:
    """把已请求取消、且仍处于可取消状态的任务落成 CANCELLED 并退款。

    仍有流水线步骤处于 PROCESSING 时直接返回 False：在途步骤返回前不退款。
    调用方若要提交本次取消，须先把本步骤移出 PROCESSING。

    Returns:
        True 表示本次调用完成了终态迁移（并已尝试退款）。
    """
    from model.ai_tool_pipeline_steps import PipelineStepModel

    if PipelineStepModel.has_processing_for_ai_tool(ai_tool_id):
        logger.info(
            "ai_tool %s cancel deferred: a pipeline step is still PROCESSING",
            ai_tool_id,
        )
        return False

    from config.constant import (
        AI_TOOL_CANCELLABLE_STATUSES,
        AI_TOOL_STATUS_CANCELLED,
        TASK_STATUS_CANCELLED,
    )
    from model import AIToolsModel, TasksModel
    from model.ai_tools_log import AIToolsLogEvent, AIToolsLogModel

    affected = AIToolsModel.transition_status(
        ai_tool_id,
        list(AI_TOOL_CANCELLABLE_STATUSES),
        AI_TOOL_STATUS_CANCELLED,
        message="任务已被用户取消",
        completed_time=datetime.now(),
        require_cancel_requested=True,
    )
    if affected == 0:
        return False

    try:
        TasksModel.update_by_task_id(ai_tool_id, status=TASK_STATUS_CANCELLED)
    except Exception as e:
        logger.warning(f"Sync tasks CANCELLED for ai_tool {ai_tool_id} failed: {e}")

    try:
        PipelineStepModel.cancel_pending_steps_by_ai_tool(ai_tool_id)
    except Exception as e:
        logger.warning(f"Cancel pending steps for ai_tool {ai_tool_id} failed: {e}")

    try:
        AIToolsLogModel.log(
            ai_tool_id,
            AIToolsLogEvent.USER_CANCELLED,
            status_to=AI_TOOL_STATUS_CANCELLED,
            message="预处理步骤结束后提交用户取消",
        )
    except Exception as e:
        logger.warning(f"Log deferred cancel for ai_tool {ai_tool_id} failed: {e}")

    try:
        from task.visual_task import _refund_computing_power
        tool = AIToolsModel.get_by_id(ai_tool_id)
        if tool:
            _refund_computing_power(tool, "用户取消排队任务")
    except Exception as e:
        logger.error(f"Refund for deferred-cancel ai_tool {ai_tool_id} failed: {e}")
    return True
