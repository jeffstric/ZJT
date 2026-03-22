from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
import asyncio
import os
import sys
from task.visual_task import generate_video_task
from task.audio_task import generate_audio_task
from task.token_task import process_token_task
from functools import partial


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局调度器实例
scheduler = None
# 文件锁
_lock_fd = None
_LOCK_FILE = None


def _run_async_task(async_func, *args, **kwargs):
    """
    在同步调度器中运行异步任务的包装函数
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(async_func(*args, **kwargs))
        loop.close()
    except Exception as e:
        logger.error(f"Error running async task: {e}")
        import traceback
        logger.error(traceback.format_exc())


def _acquire_scheduler_lock():
    """获取调度器文件锁，防止多个进程重复运行"""
    global _lock_fd, _LOCK_FILE

    # 获取项目根目录
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _LOCK_FILE = os.path.join(current_dir, "scheduler.lock")

    try:
        _lock_fd = open(_LOCK_FILE, 'w')
        if sys.platform == 'win32':
            import msvcrt
            msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        logger.info(f"Scheduler lock acquired. PID: {os.getpid()}")
        return True
    except (IOError, OSError):
        logger.warning("Another scheduler instance is already running. Skipping scheduler initialization.")
        return False


def _release_scheduler_lock():
    """释放调度器文件锁"""
    global _lock_fd
    if _lock_fd:
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
            logger.info("Scheduler lock released.")
        except Exception as e:
            logger.error(f"Error releasing scheduler lock: {e}")


def init_scheduler(app):
    """
    初始化定时任务调度器
    """
    global scheduler

    # 尝试获取文件锁
    if not _acquire_scheduler_lock():
        logger.info("Scheduler not started due to lock conflict.")
        return
    
    scheduler = BackgroundScheduler()
    
    # 创建一个带有app参数的任务函数
    task_with_app_video = partial(generate_video_task, app=app)
    task_with_app_audio = partial(_run_async_task, generate_audio_task, app=app)
    task_with_app_token = partial(process_token_task, app=app)
    
    logger.info('启用视频生成任务')
    scheduler.add_job(
        func=task_with_app_video,
        trigger=IntervalTrigger(seconds=11),
        id='generate_video',
        name='Generate video every 11 seconds',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    logger.info('启用音频生成任务')
    scheduler.add_job(
        func=task_with_app_audio,
        trigger=IntervalTrigger(seconds=7),
        id='generate_audio',
        name='Generate audio every 7 seconds',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # Token日志处理任务
    logger.info('启用Token日志处理任务')
    scheduler.add_job(
        func=task_with_app_token,
        trigger=IntervalTrigger(seconds=6),
        id='process_token',
        name='Process token logs every 6 seconds',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # 媒体缓存清理任务
    from config.config_util import get_dynamic_config_value
    cleanup_enabled = get_dynamic_config_value("media_cache", "enabled", default=True)
    cleanup_interval_hours = get_dynamic_config_value("media_cache", "cleanup_interval_hours", default=24)
    cleanup_on_startup = get_dynamic_config_value("media_cache", "cleanup_on_startup", default=True)

    if cleanup_enabled:
        from utils.media_cache import cleanup_cache

        # 启动时执行一次清理
        if cleanup_on_startup:
            logger.info('执行启动时媒体缓存清理')
            try:
                cleanup_cache()
            except Exception as e:
                logger.error(f"启动时清理缓存失败: {e}")

        # 添加定时清理任务
        logger.info(f'启用媒体缓存清理任务，间隔 {cleanup_interval_hours} 小时')
        scheduler.add_job(
            func=cleanup_cache,
            trigger=IntervalTrigger(hours=cleanup_interval_hours),
            id='cleanup_media_cache',
            name=f'Cleanup media cache every {cleanup_interval_hours} hours',
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )

    # 聊天会话清理任务
    logger.info('启用聊天会话清理任务')
    from task.session_cleanup import cleanup_expired_sessions
    task_with_app_session = partial(cleanup_expired_sessions, app=app)

    scheduler.add_job(
        func=task_with_app_session,
        trigger=IntervalTrigger(hours=6),  # 每6小时执行一次
        id='cleanup_sessions',
        name='Cleanup expired chat sessions every 6 hours',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # 启动调度器
    scheduler.start()
    logger.info("定时任务启动成功")

def shutdown_scheduler():
    """
    关闭调度器
    """
    global scheduler
    if scheduler:
        scheduler.shutdown()
    _release_scheduler_lock()
