"""
Session Cleanup Task - Scheduled task to clean up expired chat sessions
"""
import os
import shutil
from datetime import datetime, timedelta
from model.chat_sessions import ChatSessionsModel
import logging

logger = logging.getLogger(__name__)

# 营销图片存储的基础目录（相对于应用根目录）
_MARKETING_PIC_RELATIVE_DIR = os.path.join('upload', 'marketing', 'pic')
# 营销视频存储的基础目录（相对于应用根目录）
_MARKETING_VIDEO_RELATIVE_DIR = os.path.join('upload', 'marketing', 'video')
# 营销音频存储的基础目录（相对于应用根目录）
_MARKETING_AUDIO_RELATIVE_DIR = os.path.join('upload', 'marketing', 'audio')


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

        # 清理孤立的营销图片目录
        try:
            _cleanup_orphan_marketing_images()
        except Exception as e:
            logger.error(f"[Session Cleanup] Failed to cleanup orphan marketing images: {e}")

        # 清理孤立的营销视频目录
        try:
            _cleanup_orphan_marketing_videos()
        except Exception as e:
            logger.error(f"[Session Cleanup] Failed to cleanup orphan marketing videos: {e}")

        # 清理孤立的营销音频目录
        try:
            _cleanup_orphan_marketing_audios()
        except Exception as e:
            logger.error(f"[Session Cleanup] Failed to cleanup orphan marketing audios: {e}")

        return deleted_count

    except Exception as e:
        logger.error(f"[Session Cleanup] Failed to cleanup expired sessions: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0


def _cleanup_orphan_marketing_images():
    """
    清理孤立的营销图片目录

    ⚠️ 代码重复警告：此函数与 _cleanup_orphan_marketing_videos / _cleanup_orphan_marketing_audios
    逻辑几乎完全相同，仅 base_dir 路径不同。维护时需同步修改三处。

    扫描 upload/marketing/pic/ 目录下的所有子目录（即 session_id 目录），
    如果对应的 session 在数据库中不存在，则删除该目录。
    """
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base_dir = os.path.join(app_dir, _MARKETING_PIC_RELATIVE_DIR)

    if not os.path.isdir(base_dir):
        return

    cleaned = 0
    total = 0

    try:
        entries = os.listdir(base_dir)
    except Exception as e:
        logger.error(f"[Session Cleanup] Failed to list marketing pic directory: {e}")
        return

    for entry in entries:
        entry_path = os.path.join(base_dir, entry)
        if not os.path.isdir(entry_path):
            continue

        total += 1

        # 检查数据库中是否存在该 session
        try:
            exists = ChatSessionsModel.session_exists(entry)
        except Exception as e:
            logger.warning(f"[Session Cleanup] 无法确认 session {entry} 是否存在，跳过清理: {e}")
            continue

        if not exists:
            try:
                shutil.rmtree(entry_path)
                cleaned += 1
                logger.info(f"[Session Cleanup] Removed orphan marketing image directory: {entry}")
            except Exception as e:
                logger.error(f"[Session Cleanup] Failed to remove orphan directory {entry}: {e}")

    if cleaned > 0:
        logger.info(f"[Session Cleanup] Cleaned up {cleaned}/{total} orphan marketing image directories")
    else:
        logger.debug(f"[Session Cleanup] No orphan marketing image directories found ({total} directories checked)")


def _cleanup_orphan_marketing_videos():
    """
    清理孤立的营销视频目录

    扫描 upload/marketing/video/ 目录下的所有子目录（即 session_id 目录），
    如果对应的 session 在数据库中不存在，则删除该目录。
    用于清理历史遗留的孤立数据。
    """
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base_dir = os.path.join(app_dir, _MARKETING_VIDEO_RELATIVE_DIR)

    if not os.path.isdir(base_dir):
        return

    cleaned = 0
    total = 0

    try:
        entries = os.listdir(base_dir)
    except Exception as e:
        logger.error(f"[Session Cleanup] Failed to list marketing video directory: {e}")
        return

    for entry in entries:
        entry_path = os.path.join(base_dir, entry)
        if not os.path.isdir(entry_path):
            continue

        total += 1

        # 检查数据库中是否存在该 session
        try:
            exists = ChatSessionsModel.session_exists(entry)
        except Exception as e:
            logger.warning(f"[Session Cleanup] 无法确认 session {entry} 是否存在，跳过清理: {e}")
            continue

        if not exists:
            try:
                shutil.rmtree(entry_path)
                cleaned += 1
                logger.info(f"[Session Cleanup] Removed orphan marketing video directory: {entry}")
            except Exception as e:
                logger.error(f"[Session Cleanup] Failed to remove orphan directory {entry}: {e}")

    if cleaned > 0:
        logger.info(f"[Session Cleanup] Cleaned up {cleaned}/{total} orphan marketing video directories")
    else:
        logger.debug(f"[Session Cleanup] No orphan marketing video directories found ({total} directories checked)")


def _cleanup_orphan_marketing_audios():
    """
    清理孤立的营销音频目录

    扫描 upload/marketing/audio/ 目录下的所有子目录（即 session_id 目录），
    如果对应的 session 在数据库中不存在，则删除该目录。
    """
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    base_dir = os.path.join(app_dir, _MARKETING_AUDIO_RELATIVE_DIR)

    if not os.path.isdir(base_dir):
        return

    cleaned = 0
    total = 0

    try:
        entries = os.listdir(base_dir)
    except Exception as e:
        logger.error(f"[Session Cleanup] Failed to list marketing audio directory: {e}")
        return

    for entry in entries:
        entry_path = os.path.join(base_dir, entry)
        if not os.path.isdir(entry_path):
            continue

        total += 1

        try:
            exists = ChatSessionsModel.session_exists(entry)
        except Exception as e:
            logger.warning(f"[Session Cleanup] 无法确认 session {entry} 是否存在，跳过清理: {e}")
            continue

        if not exists:
            try:
                shutil.rmtree(entry_path)
                cleaned += 1
                logger.info(f"[Session Cleanup] Removed orphan marketing audio directory: {entry}")
            except Exception as e:
                logger.error(f"[Session Cleanup] Failed to remove orphan directory {entry}: {e}")

    if cleaned > 0:
        logger.info(f"[Session Cleanup] Cleaned up {cleaned}/{total} orphan marketing audio directories")
    else:
        logger.debug(f"[Session Cleanup] No orphan marketing audio directories found ({total} directories checked)")
