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

    ⚠️ 每次调用创建新的事件循环，不复用。loop.close() 会释放所有关联资源。
    仅适用于短生命周期的异步任务，不要在此运行持续性连接池或后台任务。
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


def _is_stale_lock():
    """检查锁文件是否来自已死亡的进程"""
    if not _LOCK_FILE or not os.path.exists(_LOCK_FILE):
        return False
    try:
        with open(_LOCK_FILE, 'r') as f:
            pid_str = f.read().strip()
        if not pid_str:
            # 空文件 = 锁写入失败残留
            return True
        pid = int(pid_str)
        # 检查 PID 是否存活
        if sys.platform == 'win32':
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x100000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return False
            return True
        else:
            # Linux: os.kill(pid, 0) 不发送信号，只检查进程是否存在
            try:
                os.kill(pid, 0)
                return False  # 进程存活，锁有效
            except (ProcessLookupError, PermissionError):
                return True   # 进程已死，锁无效
    except (ValueError, OSError):
        return True  # 文件内容异常，视为残留


def _force_acquire_lock():
    """强制获取锁（清除残留锁后重新获取）"""
    global _lock_fd, _LOCK_FILE
    # 删除残留锁文件
    if os.path.exists(_LOCK_FILE):
        os.remove(_LOCK_FILE)
    # 重新创建
    _lock_fd = open(_LOCK_FILE, 'w')
    if sys.platform == 'win32':
        import msvcrt
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
    logger.info(f"Scheduler lock force-acquired after clearing stale lock. PID: {os.getpid()}")


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
            _lock_fd.write(str(os.getpid()))
            _lock_fd.flush()
            msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _lock_fd.write(str(os.getpid()))
            _lock_fd.flush()
        logger.info(f"Scheduler lock acquired. PID: {os.getpid()}")
        return True
    except (IOError, OSError):
        # 锁获取失败，检查是否为残留死锁
        _lock_fd.close()
        _lock_fd = None
        if _is_stale_lock():
            logger.warning("Detected stale scheduler lock from dead process. Clearing and retrying...")
            _force_acquire_lock()
            return True
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


def _reset_orphan_sync_tasks():
    """
    重置孤儿同步任务

    服务重启后，进程池队列丢失，SYNC_QUEUED 状态的任务需要重置为 PENDING
    这可能导致少量重复请求，但比任务永久卡住要好
    """
    try:
        from model import AIToolsModel, TasksModel
        from config.constant import (
            AI_TOOL_STATUS_SYNC_QUEUED, AI_TOOL_STATUS_PENDING,
            TASK_STATUS_SYNC_QUEUED, TASK_STATUS_QUEUED,
        )

        # 重置 AITools 表中的孤儿任务
        ai_tools_count = AIToolsModel.reset_status(
            from_status=AI_TOOL_STATUS_SYNC_QUEUED,
            to_status=AI_TOOL_STATUS_PENDING
        )

        # 重置 Tasks 表中的孤儿任务
        tasks_count = TasksModel.reset_status(
            from_status=TASK_STATUS_SYNC_QUEUED,
            to_status=TASK_STATUS_QUEUED
        )

        if ai_tools_count > 0 or tasks_count > 0:
            logger.info(f"Reset orphan sync tasks: AITools={ai_tools_count}, Tasks={tasks_count}")

    except Exception as e:
        logger.error(f"Failed to reset orphan sync tasks: {e}")


def _reset_orphan_processing_tasks():
    """
    重置孤儿处理中任务

    Scheduler 启动时，检查 status=1(PROCESSING) 且 project_id=NULL
    且 update_time 超过阈值的任务，重置为 PENDING 让其重新执行。

    判定条件：
    - status = 1 (PROCESSING)
    - project_id IS NULL（未成功提交到外部API）
    - result_url IS NULL（未产出结果）
    - update_time < NOW() - 20分钟（排除刚被取走正在处理的任务）

    安全性：
    - 只重置 project_id=NULL 的任务，不会导致外部 API 重复计费
    - 20分钟阈值远大于同步超时（5分钟），不会误杀正常任务
    """
    ORPHAN_THRESHOLD_MINUTES = 20

    try:
        from model import AIToolsModel, TasksModel
        from model.database import execute_update, execute_query
        from config.constant import (
            AI_TOOL_STATUS_PROCESSING, AI_TOOL_STATUS_PENDING,
            TASK_STATUS_PROCESSING, TASK_STATUS_QUEUED,
        )

        # 1. 查找符合条件的孤儿任务 ID
        find_sql = """
            SELECT id FROM ai_tools
            WHERE status = %s
              AND project_id IS NULL
              AND result_url IS NULL
              AND update_time < NOW() - INTERVAL %s MINUTE
        """
        orphan_rows = execute_query(find_sql, (AI_TOOL_STATUS_PROCESSING, ORPHAN_THRESHOLD_MINUTES), fetch_all=True)
        if not orphan_rows:
            return

        orphan_ids = [row['id'] for row in orphan_rows]
        logger.info(f"Found {len(orphan_ids)} orphan processing tasks: {orphan_ids}")

        # 2. 先释放同步执行器中可能残留的 future/worker，不退款，不改 FAILED。
        try:
            from task.sync_task_executor import SyncTaskExecutor

            executor = SyncTaskExecutor.get_instance()
            if executor.is_running():
                for tid in orphan_ids:
                    if executor.force_release_task(tid, refund=False):
                        logger.info(f"Force released orphan sync future without refund for task {tid}")
        except Exception as exc:
            logger.error(f"Failed to release orphan futures: {exc}")

        # 3. 重置 ai_tools 表
        placeholders = ','.join(['%s'] * len(orphan_ids))
        ai_tools_sql = f"UPDATE ai_tools SET status = %s, update_time = NOW() WHERE id IN ({placeholders})"
        ai_tools_count = execute_update(ai_tools_sql, (AI_TOOL_STATUS_PENDING, *orphan_ids))

        # 4. 重置 tasks 表（task_id 对应 ai_tools.id）
        tasks_sql = f"UPDATE tasks SET status = %s, next_trigger = NOW() WHERE task_id IN ({placeholders}) AND status = %s"
        tasks_count = execute_update(tasks_sql, (TASK_STATUS_QUEUED, *orphan_ids, TASK_STATUS_PROCESSING))

        logger.info(f"Reset orphan processing tasks: AITools={ai_tools_count}, Tasks={tasks_count}, IDs={orphan_ids}")

    except Exception as e:
        logger.error(f"Failed to reset orphan processing tasks: {e}")


def init_scheduler(app):
    """
    初始化定时任务调度器
    """
    global scheduler

    # 尝试获取文件锁
    if not _acquire_scheduler_lock():
        logger.info("Scheduler not started due to lock conflict.")
        return

    # 重置孤儿同步任务（服务重启后进程池队列丢失）
    _reset_orphan_sync_tasks()

    # 重置孤儿处理中任务（进程崩溃导致 status=1 但未提交成功的任务）
    _reset_orphan_processing_tasks()

    scheduler = BackgroundScheduler()

    # 启动同步任务执行器
    from task.sync_task_executor import SyncTaskExecutor, process_sync_task_results
    from config.config_util import get_dynamic_config_value

    executor = SyncTaskExecutor.get_instance()
    if executor.start():
        logger.info("同步任务执行器启动成功")

        # 添加同步任务结果检查调度任务
        check_interval = get_dynamic_config_value("sync_task", "check_interval", default=5)
        logger.info(f'启用同步任务结果检查，间隔 {check_interval} 秒')
        scheduler.add_job(
            func=process_sync_task_results,
            trigger=IntervalTrigger(seconds=check_interval),
            id='check_sync_tasks',
            name=f'Check sync task results every {check_interval} seconds',
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
    else:
        logger.warning("同步任务执行器启动失败，同步任务将使用原有流程")

    # 创建一个带有app参数的任务函数
    task_with_app_video = partial(generate_video_task, app=app)
    task_with_app_audio = partial(_run_async_task, generate_audio_task, app=app)
    task_with_app_token = partial(process_token_task, app=app)

    logger.info('启用视频生成任务')
    scheduler.add_job(
        func=task_with_app_video,
        trigger=IntervalTrigger(seconds=5),
        id='generate_video',
        name='Generate video every 5 seconds',  # ⚠️ 实际间隔5秒，之前name描述错误
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    logger.info('启用音频生成任务')
    scheduler.add_job(
        func=task_with_app_audio,
        trigger=IntervalTrigger(seconds=13),
        id='generate_audio',
        name='Generate audio every 13 seconds',  # ⚠️ 实际间隔13秒，之前name描述错误
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

    # 宫格生图任务处理
    logger.info('启用宫格生图任务处理')
    from task.grid_image_task import process_grid_image_tasks
    task_with_app_grid_image = partial(process_grid_image_tasks, app=app)

    scheduler.add_job(
        func=task_with_app_grid_image,
        trigger=IntervalTrigger(seconds=10),  # 每10秒执行一次
        id='process_grid_image_tasks',
        name='Process grid image tasks every 10 seconds',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # 场景多角度生图任务处理
    logger.info('启用场景多角度生图任务处理')
    from task.location_multi_angle_task import process_pending_location_multi_angle_tasks

    scheduler.add_job(
        func=process_pending_location_multi_angle_tasks,
        trigger=IntervalTrigger(seconds=17),  # 每17秒执行一次
        id='process_location_multi_angle_tasks',
        name='Process location multi-angle tasks every 17 seconds',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # 实现方统计缓存刷新任务
    logger.info('启用实现方统计缓存刷新任务，每1小时执行一次')
    from task.stats_cache_task import refresh_implementation_stats_cache
    scheduler.add_job(
        func=refresh_implementation_stats_cache,
        trigger=IntervalTrigger(hours=1),  # 每1小时执行一次
        id='refresh_implementation_stats_cache',
        name='Refresh implementation stats cache every 1 hour',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # Agent任务清理（清理24小时前的已完成任务和消息）
    logger.info('启用Agent任务清理任务，每6小时执行一次')
    from task.agent_task_cleanup import cleanup_agent_tasks
    scheduler.add_job(
        func=cleanup_agent_tasks,
        trigger=IntervalTrigger(hours=6),  # 每6小时执行一次
        id='cleanup_agent_tasks',
        name='Cleanup old agent tasks every 6 hours',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # RunningHub槽位清理（清理超过2小时仍处于处理中的槽位）
    logger.info('启用RunningHub槽位清理任务，每30分钟执行一次')
    from task.runninghub_slots_cleanup import cleanup_runninghub_slots
    scheduler.add_job(
        func=cleanup_runninghub_slots,
        trigger=IntervalTrigger(minutes=30),  # 每30分钟执行一次
        id='cleanup_runninghub_slots',
        name='Cleanup stale RunningHub slots every 30 minutes',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # 孤儿任务定期恢复（status=PROCESSING 但 project_id=NULL 超过20分钟的任务）
    logger.info('启用孤儿任务定期恢复，每20分钟执行一次')
    scheduler.add_job(
        func=_reset_orphan_processing_tasks,
        trigger=IntervalTrigger(minutes=20),
        id='reset_orphan_processing_tasks',
        name='Reset orphan processing tasks every 20 minutes',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # RunningHub 异步任务轮询（音频生成等）
    logger.info('启用RunningHub异步任务轮询，每10秒执行一次')
    from task.runninghub_async_task import process_runninghub_async_tasks
    scheduler.add_job(
        func=process_runninghub_async_tasks,
        trigger=IntervalTrigger(seconds=10),
        id='process_runninghub_async_tasks',
        name='Process RunningHub async tasks every 10 seconds',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # 异步任务提交重试处理（槽位满时自动重试）
    logger.info('启用异步任务提交重试处理，每7秒执行一次')
    from task.async_task_submission import process_pending_async_task_submissions
    scheduler.add_job(
        func=process_pending_async_task_submissions,
        trigger=IntervalTrigger(seconds=7),
        id='process_pending_async_task_submissions',
        name='Process pending async task submissions every 30 seconds',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # Pipeline 步骤处理（param_prepare / before_finish 阶段）
    logger.info('启用Pipeline步骤处理，每13秒执行一次')
    from task.pipeline_processor import PipelineProcessor
    task_with_app_pipeline = partial(_run_async_task, PipelineProcessor.process_all_pending_steps)
    scheduler.add_job(
        func=task_with_app_pipeline,
        trigger=IntervalTrigger(seconds=13),
        id='process_pipeline_steps',
        name='Process pipeline steps every 10 seconds',
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

    # 关闭同步任务执行器
    try:
        from task.sync_task_executor import SyncTaskExecutor
        executor = SyncTaskExecutor.get_instance()
        if executor.is_running():
            executor.shutdown(wait=True)
            logger.info("同步任务执行器已关闭")
    except Exception as e:
        logger.error(f"关闭同步任务执行器失败: {e}")

    if scheduler:
        try:
            scheduler.shutdown()
        except Exception as e:
            logger.warning(f"Scheduler shutdown error (ignored): {e}")
    _release_scheduler_lock()
