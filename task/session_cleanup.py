"""
Session Cleanup Task - Scheduled task to clean up expired chat sessions
"""
from datetime import datetime, timedelta
from model.chat_sessions import ChatSessionsModel
import logging

logger = logging.getLogger(__name__)


def cleanup_expired_sessions(app=None):
    """
    Clean up expired chat sessions

    This task marks sessions as inactive (soft delete) if their expiration time
    has passed. It is designed to be run periodically by the scheduler.

    Args:
        app: FastAPI app instance (optional, for consistency with other tasks)

    Returns:
        Number of sessions cleaned up
    """
    try:
        # Delete all expired sessions (no grace period)
        cutoff_time = datetime.now()
        logger.info(f"[Session Cleanup] Starting cleanup, cutoff_time: {cutoff_time}")

        deleted_count = ChatSessionsModel.delete_expired_sessions(before_date=cutoff_time)

        if deleted_count > 0:
            logger.info(f"[Session Cleanup] Cleaned up {deleted_count} expired chat sessions")
        else:
            logger.debug(f"[Session Cleanup] No expired chat sessions to clean up (cutoff: {cutoff_time})")

        return deleted_count

    except Exception as e:
        logger.error(f"[Session Cleanup] Failed to cleanup expired sessions: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0
