"""清理直传后从未 confirm 的工作流七牛对象。

只删除 upload/workflow/ 前缀、没有 media_file_mapping、且 putTime 早于宽限期的对象。
宽限期长于上传 token 有效期，避免删掉还在上传或尚未 confirm 的对象。
调度进程里运行，七牛 SDK 的同步调用允许阻塞本进程。
"""
import logging
import time

from config.constant import (
    QINIU_DIRECT_UPLOAD_ORPHAN_DELETE_LIMIT,
    QINIU_DIRECT_UPLOAD_ORPHAN_GRACE_SECONDS,
    QINIU_DIRECT_UPLOAD_ORPHAN_SCAN_LIMIT,
    QINIU_WORKFLOW_UPLOAD_KEY_PREFIX,
)

logger = logging.getLogger(__name__)

_PUT_TIME_TICKS_PER_SECOND = 10_000_000


def qiniu_put_time_expired(put_time, now_seconds: float, grace_seconds: int) -> bool:
    """putTime 是自 Unix 纪元起的 100 纳秒计数。缺失或无法解析时不删除。"""
    if put_time is None or isinstance(put_time, bool):
        return False
    try:
        put_seconds = int(put_time) / _PUT_TIME_TICKS_PER_SECOND
    except (TypeError, ValueError):
        return False
    return (now_seconds - put_seconds) >= grace_seconds


def select_orphan_keys(items, now_seconds: float, is_mapped, grace_seconds: int,
                       prefix: str, delete_limit: int) -> list:
    """从列举结果里选出可删除的 key。is_mapped 抛错的对象跳过。"""
    chosen = []
    limit = max(int(delete_limit or 0), 0)
    for item in items or []:
        if len(chosen) >= limit:
            break
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        if not key.startswith(prefix) or key == prefix or key.endswith("/"):
            continue
        if not qiniu_put_time_expired(item.get("putTime"), now_seconds, grace_seconds):
            continue
        try:
            mapped = bool(is_mapped(key))
        except Exception as e:
            logger.warning(f"Skip orphan check for {key}: {e}")
            continue
        if mapped:
            continue
        chosen.append(key)
    return chosen


def cleanup_orphan_workflow_uploads() -> int:
    """删除一批孤儿对象。配置缺失或列举失败时返回 0。"""
    from model.media_file_mapping import MediaFileMappingModel
    from utils.file_storage import get_file_storage

    try:
        storage = get_file_storage(section="qiniu_long_term")
    except Exception as e:
        logger.info(f"Skip qiniu orphan cleanup: storage unavailable ({e})")
        return 0
    if not hasattr(storage, "list_object_stats") or not hasattr(storage, "delete_sync"):
        logger.info("Skip qiniu orphan cleanup: storage backend has no origin listing")
        return 0
    try:
        items = storage.list_object_stats(
            QINIU_WORKFLOW_UPLOAD_KEY_PREFIX,
            QINIU_DIRECT_UPLOAD_ORPHAN_SCAN_LIMIT,
        )
    except Exception as e:
        logger.error(f"Qiniu orphan list failed: {e}")
        return 0

    def _mapped(key: str) -> bool:
        return MediaFileMappingModel.get_by_local_path(key) is not None

    keys = select_orphan_keys(
        items,
        time.time(),
        _mapped,
        QINIU_DIRECT_UPLOAD_ORPHAN_GRACE_SECONDS,
        QINIU_WORKFLOW_UPLOAD_KEY_PREFIX,
        QINIU_DIRECT_UPLOAD_ORPHAN_DELETE_LIMIT,
    )
    deleted = 0
    for key in keys:
        try:
            if storage.delete_sync(key):
                deleted += 1
                logger.info(f"Deleted orphan qiniu object {key}")
            else:
                logger.warning(f"Failed to delete orphan qiniu object {key}")
        except Exception as e:
            logger.warning(f"Delete orphan qiniu object {key} failed: {e}")
    return deleted
