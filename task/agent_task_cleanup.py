"""
Agent Task Cleanup Task - Scheduled task to clean up old agent tasks and messages
"""
from model.agent_tasks import AgentTasksModel
from model.agent_task_messages import AgentTaskMessagesModel
import logging

logger = logging.getLogger(__name__)


def cleanup_agent_tasks(max_age_hours: int = 24):
    """
    Clean up old agent tasks and messages

    This task deletes completed/failed/cancelled tasks and their messages
    that are older than max_age_hours. It is designed to be run periodically
    by the scheduler.

    Args:
        max_age_hours: Maximum age in hours for tasks to keep (default: 24)

    Returns:
        Tuple of (deleted_tasks, deleted_messages)
    """
    try:
        logger.info(f"[Agent Task Cleanup] Starting cleanup, max_age_hours: {max_age_hours}")

        # 先删除消息（因为消息依赖任务）
        deleted_messages = AgentTaskMessagesModel.delete_old_messages(max_age_hours)

        # 再删除任务
        deleted_tasks = AgentTasksModel.delete_old_tasks(max_age_hours)

        if deleted_tasks > 0 or deleted_messages > 0:
            logger.info(f"[Agent Task Cleanup] Cleaned up {deleted_tasks} tasks and {deleted_messages} messages")
        else:
            logger.debug(f"[Agent Task Cleanup] No old tasks to clean up")

        return deleted_tasks, deleted_messages

    except Exception as e:
        logger.error(f"[Agent Task Cleanup] Failed to cleanup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0, 0
