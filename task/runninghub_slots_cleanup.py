"""
RunningHub Slots Cleanup Task - 定时清理超时的 RunningHub 槽位

超过指定时间（默认2小时）仍处于"处理中"状态的槽位，自动设置为"已完成"
"""
from model.runninghub_slots import RunningHubSlotsModel
from config.config_util import get_dynamic_config_value
import logging

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MINUTES = 120  # 默认超时时间：2小时


def cleanup_runninghub_slots():
    """
    清理超时的 RunningHub 槽位

    从配置文件读取超时时间，默认为2小时（120分钟）
    将超时的处理中槽位自动设置为已完成

    Returns:
        清理的槽位数量
    """
    try:
        timeout_minutes = get_dynamic_config_value(
            "runninghub", "slot_timeout_minutes", default=DEFAULT_TIMEOUT_MINUTES
        )

        logger.info(f"[RunningHub Slots Cleanup] Starting cleanup, timeout: {timeout_minutes} minutes")

        cleaned_count = RunningHubSlotsModel.cleanup_stale_slots(timeout_minutes)

        if cleaned_count > 0:
            logger.warning(f"[RunningHub Slots Cleanup] Cleaned up {cleaned_count} stale slots (timeout: {timeout_minutes}min)")
        else:
            logger.debug(f"[RunningHub Slots Cleanup] No stale slots to clean up")

        return cleaned_count

    except Exception as e:
        logger.error(f"[RunningHub Slots Cleanup] Failed to cleanup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0
