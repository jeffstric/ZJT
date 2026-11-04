"""清理直传后从未 confirm 的工作流七牛对象。

超过宽限期且没有 media_file_mapping 的 upload/workflow/ 对象，先挪到
wait_delete/YYYY-MM-DD/<原 key>。目录日期满保留天数后才真正删除。
宽限期长于上传 token 有效期，避免挪走还在上传或尚未 confirm 的对象。
调度进程里运行，七牛 SDK 的同步调用允许阻塞本进程。
"""
import logging
import time
from datetime import date, datetime

from config.constant import (
    QINIU_DIRECT_UPLOAD_ORPHAN_DELETE_LIMIT,
    QINIU_DIRECT_UPLOAD_ORPHAN_GRACE_SECONDS,
    QINIU_DIRECT_UPLOAD_ORPHAN_SCAN_LIMIT,
    QINIU_DIRECT_UPLOAD_WAIT_DELETE_PREFIX,
    QINIU_DIRECT_UPLOAD_WAIT_DELETE_RETAIN_DAYS,
    QINIU_WORKFLOW_UPLOAD_KEY_PREFIX,
)

logger = logging.getLogger(__name__)

_PUT_TIME_TICKS_PER_SECOND = 10_000_000
_WAIT_DELETE_DAY_FORMAT = "%Y-%m-%d"


def qiniu_put_time_expired(put_time, now_seconds: float, grace_seconds: int) -> bool:
    """putTime 是自 Unix 纪元起的 100 纳秒计数。缺失或无法解析时不处理。"""
    if put_time is None or isinstance(put_time, bool):
        return False
    try:
        put_seconds = int(put_time) / _PUT_TIME_TICKS_PER_SECOND
    except (TypeError, ValueError):
        return False
    return (now_seconds - put_seconds) >= grace_seconds


def select_orphan_keys(items, now_seconds: float, is_mapped, grace_seconds: int,
                       prefix: str, delete_limit: int) -> list:
    """从列举结果里选出可挪入待删目录的 key。is_mapped 抛错的对象跳过。"""
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


def build_wait_delete_key(original_key: str, day: str, wait_prefix: str) -> str:
    """原 key 整段保留，前面加上 wait_delete/YYYY-MM-DD/。"""
    key = str(original_key or "").strip().lstrip("/")
    folder = str(day or "").strip()
    prefix = str(wait_prefix or "").strip()
    if not key or not folder or not prefix:
        return ""
    if not prefix.endswith("/"):
        prefix += "/"
    return f"{prefix}{folder}/{key}"


def wait_delete_folder_date(key: str, wait_prefix: str):
    """解析 wait_delete/YYYY-MM-DD/<原 key> 里的日期。格式不对时返回 None。"""
    text = str(key or "")
    prefix = str(wait_prefix or "")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    if not prefix or not text.startswith(prefix) or text == prefix or text.endswith("/"):
        return None
    day, sep, remainder = text[len(prefix):].partition("/")
    if not sep or not remainder:
        return None
    try:
        return datetime.strptime(day, _WAIT_DELETE_DAY_FORMAT).date()
    except ValueError:
        return None


def select_expired_wait_delete_keys(items, today, retain_days: int, wait_prefix: str,
                                    delete_limit: int) -> list:
    """选出目录日期已满保留天数的待删对象。日期解析不了的不删。"""
    chosen = []
    limit = max(int(delete_limit or 0), 0)
    days = int(retain_days or 0)
    if isinstance(today, datetime):
        today = today.date()
    if days < 1 or not isinstance(today, date):
        return []
    for item in items or []:
        if len(chosen) >= limit:
            break
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        folder_day = wait_delete_folder_date(key, wait_prefix)
        if folder_day is None:
            continue
        if (today - folder_day).days >= days:
            chosen.append(key)
    return chosen


def _list_object_stats(storage, prefix: str, limit: int) -> list:
    try:
        items = storage.list_object_stats(prefix, limit)
    except Exception as e:
        logger.error(f"Qiniu orphan list failed: prefix={prefix}, error={e}")
        return []
    return items or []


def cleanup_orphan_workflow_uploads(today=None) -> int:
    """把一批孤儿对象挪入待删目录，并删除已满保留期的对象。返回本次挪走的数量。"""
    from model.media_file_mapping import MediaFileMappingModel
    from utils.file_storage import get_file_storage

    if today is None:
        today = datetime.now().date()
    elif isinstance(today, datetime):
        today = today.date()

    try:
        storage = get_file_storage(section="qiniu_long_term")
    except Exception as e:
        logger.info(f"Skip qiniu orphan cleanup: storage unavailable ({e})")
        return 0
    if not hasattr(storage, "list_object_stats"):
        logger.info("Skip qiniu orphan cleanup: storage backend has no origin listing")
        return 0

    def _mapped(key: str) -> bool:
        return MediaFileMappingModel.get_by_local_path(key) is not None

    moved = 0
    if hasattr(storage, "move_sync"):
        items = _list_object_stats(
            storage,
            QINIU_WORKFLOW_UPLOAD_KEY_PREFIX,
            QINIU_DIRECT_UPLOAD_ORPHAN_SCAN_LIMIT,
        )
        keys = select_orphan_keys(
            items,
            time.time(),
            _mapped,
            QINIU_DIRECT_UPLOAD_ORPHAN_GRACE_SECONDS,
            QINIU_WORKFLOW_UPLOAD_KEY_PREFIX,
            QINIU_DIRECT_UPLOAD_ORPHAN_DELETE_LIMIT,
        )
        day = today.strftime(_WAIT_DELETE_DAY_FORMAT)
        for key in keys:
            dest = build_wait_delete_key(key, day, QINIU_DIRECT_UPLOAD_WAIT_DELETE_PREFIX)
            if not dest:
                continue
            try:
                ok = bool(storage.move_sync(key, dest))
            except Exception as e:
                logger.warning(f"Quarantine qiniu object {key} failed: {e}")
                ok = False
            if ok:
                moved += 1
                logger.info(f"Quarantined qiniu object {key} -> {dest}")
            else:
                logger.warning(f"Failed to quarantine qiniu object {key}")
    else:
        logger.info("Skip qiniu orphan quarantine: storage backend has no move")

    purged = 0
    if hasattr(storage, "delete_sync"):
        wait_items = _list_object_stats(
            storage,
            QINIU_DIRECT_UPLOAD_WAIT_DELETE_PREFIX,
            QINIU_DIRECT_UPLOAD_ORPHAN_SCAN_LIMIT,
        )
        expired = select_expired_wait_delete_keys(
            wait_items,
            today,
            QINIU_DIRECT_UPLOAD_WAIT_DELETE_RETAIN_DAYS,
            QINIU_DIRECT_UPLOAD_WAIT_DELETE_PREFIX,
            QINIU_DIRECT_UPLOAD_ORPHAN_DELETE_LIMIT,
        )
        for key in expired:
            try:
                if storage.delete_sync(key):
                    purged += 1
                    logger.info(f"Deleted expired wait_delete qiniu object {key}")
                else:
                    logger.warning(f"Failed to delete expired wait_delete qiniu object {key}")
            except Exception as e:
                logger.warning(f"Delete expired wait_delete qiniu object {key} failed: {e}")
    else:
        logger.info("Skip qiniu wait_delete purge: storage backend has no delete")

    logger.info(f"Qiniu orphan cleanup quarantined={moved} purged={purged}")
    return moved
