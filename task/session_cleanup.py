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
        # Delete sessions that expired more than 24 hours ago
        # This gives a grace period before cleanup
        cutoff_time = datetime.now() - timedelta(hours=24)

        deleted_count = ChatSessionsModel.delete_expired_sessions(before_date=cutoff_time)

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired chat sessions")
        else:
            logger.debug("No expired chat sessions to clean up")

        return deleted_count

    except Exception as e:
        logger.error(f"Failed to cleanup expired sessions: {e}")
        return 0
