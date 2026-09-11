from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
import asyncio
import os
import signal
from typing import Optional
import sys
from task.visual_task import generate_video_task
from task.audio_task import generate_audio_task
from task.token_task import process_token_task
from task.download_queue_task import process_download_queue
from task.subscription_renewal_task import process_subscription_renewals
from functools import partial
from config.constant import StoryboardAutoGenerateConstants, VoiceReplaceConstants, Edition, SubscriptionConstants

from config.constant import DOWNLOAD_POLL_INTERVAL
from config.constant import LICENSE_REBOOTSTRAP_INTERVAL_SECONDS


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局调度器实例
scheduler = None
# 文件锁
_lock_fd = None
_LOCK_FILE = None
# at_fork 钩子只注册一次
_atfork_hook_installed = False


def _reset_forked_child_signals():
    """fork 子进程丢掉父进程装的 cleanup handler。

    run_scheduler / run_script_split_worker 把 SIGTERM 接到 cleanup()->sys.exit(0)。
    该处理器随 fork 继承；SyncManager / ProcessPool worker 收到 SIGTERM 时
    会跑调度器 cleanup 而非默认终止（无 traceback、unix socket 文件残留）。
    PR_SET_PDEATHSIG 在 fork 时被内核清除，不会链式传到子进程。
    """
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, signal.SIG_DFL)
        except (ValueError, OSError):
            pass
    sighup = getattr(signal, "SIGHUP", None)
    if sighup is not None:
        try:
            signal.signal(sighup, signal.SIG_DFL)
        except (ValueError, OSError):
            pass


def _os_close_inherited_lock_fd(lock_fd):
    """关闭继承的锁 fd。返回 None 供调用方写回 _lock_fd。

    用普通 file.close()（flush + close fd，对象状态一致）。此前版本改用
    os.close(fileno) 并试图 patch 对象 close 为空操作——但 _io 对象禁止
    属性赋值，patch 静默失败：覆盖 _lock_fd 引用触发 __del__ 时对已关 fd
    二次 close，必抛 OSError(EBADF)（GC 噪音 + fd 复用后误关风险）。
    os.close 方案担心的"继承 IO 锁死锁"在本项目时序下不存在：锁文件的
    写入（acquire 时写 pid）只发生在主线程，fork 亦由工作线程发起，
    写锁在 fork 瞬间必然空闲。
    """
    if lock_fd is None:
        return None
    try:
        lock_fd.close()
    except Exception:
        pass
    return None


def _after_fork_in_child():
    """at_fork after_in_child：关锁 fd + 重置继承的信号处理器。"""
    global _lock_fd
    _reset_forked_child_signals()
    _lock_fd = _os_close_inherited_lock_fd(_lock_fd)


def _run_async_task(async_func, *args, **kwargs):
    """
    在同步调度器中运行异步任务的包装函数

    ⚠️ 每次调用创建新的事件循环，不复用。loop.close() 会释放所有关联资源。
    仅适用于短生命周期的异步任务，不要在此运行持续性连接池或后台任务。
    """
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(async_func(*args, **kwargs))
    except Exception as e:
        logger.error(f"Error running async task: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # close 必须在 finally：异常路径不关闭会泄漏 epoll fd + 自管道 socketpair，
        # 调度器长期运行下与其他 FD 泄漏叠加打满上限（2026-09-12 EMFILE 事故伴生缺陷）
        if loop is not None and not loop.is_closed():
            loop.close()
        # 线程上不留已关闭的 loop 引用（下次调用会 new + set，此处仅为卫生）
        asyncio.set_event_loop(None)


def _win_process_alive(pid: int) -> bool:
    """Windows 进程探活：OpenProcess + GetExitCodeProcess。

    两处历史缺陷（Windows 本机实测抓到）：
    1. ctypes 不设 argtypes/restype 时默认按 c_int 截断——64 位 HANDLE
       返回值被截断，判断不可靠；
    2. 进程已退出但句柄尚未被回收（父进程仍持有）时 OpenProcess 照样
       成功 → 误判存活。对防孤儿看门狗意味着"父已死却永远等不到退出"，
       对锁探活意味着持有者已死却诚实拒锁。必须用 GetExitCodeProcess
       区分 STILL_ACTIVE。
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    # PROCESS_QUERY_LIMITED_INFORMATION：GetExitCodeProcess 所需最小权限
    # （原用的 SYNCHRONIZE=0x100000 不足以调用 GetExitCodeProcess）
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _is_lock_holder_alive(lock_file: str) -> bool:
    """读取锁文件中的 pid，判断持有进程是否存活（仅用于日志诊断）"""
    try:
        with open(lock_file, 'r', encoding='utf-8') as f:
            pid_str = f.read().strip()
        if not pid_str.isdigit():
            return False
        pid = int(pid_str)
        if sys.platform == 'win32':
            return _win_process_alive(pid)
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # 无权限发信号不代表进程已死（如不同用户的进程），不能误判
            return True
    except (ValueError, OSError):
        return False


def _acquire_scheduler_lock(lock_file: Optional[str] = None) -> bool:
    """获取调度器文件锁，防止多个进程重复运行。

    正确性要点（修复历史缺陷：生产曾积累 31 个调度器进程）：
      - 锁文件用 'a' 模式打开（不清空、不删除持有者的 pid 记录）；
      - 只依赖 flock/msvcrt 文件锁排他，**永不删除重建锁文件**——
        旧实现的 'w' 截断 + 失败后删除重建，会让新实例抢到新 inode 的锁、
        旧持有者的锁名存实亡（批量启动/重启时必然多实例同时"持锁"）；
      - flock 随持有进程死亡由内核自动释放：持有者已死时重试 flock 必然成功，
        无需任何"残留强抢"逻辑。
    """
    global _lock_fd, _LOCK_FILE, _atfork_hook_installed

    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _LOCK_FILE = lock_file or os.path.join(current_dir, "scheduler.lock")

    for _ in range(2):
        # 先用局部变量持 fd：若本进程已持锁，覆盖 _lock_fd 会令旧 fd 被 GC
        # 关闭、旧锁随之释放，flock 的排他语义就永远不会拒绝同进程重复获取
        new_fd = open(_LOCK_FILE, 'a')
        try:
            if sys.platform == 'win32':
                import msvcrt
                # 锁文件远端字节（1MB 处），避免与 pid 内容重叠导致自身读取被拒
                new_fd.seek(1048576)
                msvcrt.locking(new_fd.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(new_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # 加锁成功后才接管 _lock_fd（旧 fd 保持打开直到此刻）
            if _lock_fd is not None:
                try:
                    _lock_fd.close()
                except Exception:
                    pass
            _lock_fd = new_fd
            _lock_fd.seek(0)
            _lock_fd.truncate(0)
            _lock_fd.write(str(os.getpid()))
            _lock_fd.flush()
            # 阻断 fork 继承：子进程不持锁 fd，也不继承 SIGTERM cleanup
            if hasattr(os, "register_at_fork") and not _atfork_hook_installed:
                os.register_at_fork(after_in_child=_after_fork_in_child)
                _atfork_hook_installed = True
            logger.info(f"Scheduler lock acquired. PID: {os.getpid()}")
            return True
        except (IOError, OSError):
            # 只关闭本次试探的新 fd；_lock_fd 是本进程已持有的锁，不能动
            try:
                new_fd.close()
            except Exception:
                pass
            if _is_lock_holder_alive(_LOCK_FILE):
                logger.warning("Another scheduler instance is already running. Skipping scheduler initialization.")
                return False
            # 文件中的 pid 已死亡：内核文件锁随进程死亡自动释放，重试一次即可获取
            logger.info("Scheduler lock was held by a dead process, retrying acquire...")

    logger.error("Scheduler lock could not be acquired after retries.")
    return False


def _release_scheduler_lock():
    """释放调度器文件锁"""
    global _lock_fd
    if _lock_fd:
        try:
            if sys.platform == 'win32':
                import msvcrt
                # 加锁时锁的是 1MB 处的字节；解锁前必须 seek 回同一位置，
                # 否则 msvcrt.locking 解的是当前文件位置的 1 字节，解锁必然失败
                # （优雅释放必打 error；进程内 shutdown 而退出时还会漏锁）
                _lock_fd.seek(1048576)
                msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
            _lock_fd = None
            logger.info("Scheduler lock released.")
        except Exception as e:
            logger.error(f"Error releasing scheduler lock: {e}")


def parent_process_dead(initial_ppid: int) -> bool:
    """防孤儿看门狗：判断启动时记录的父进程是否已死亡。

    - Linux/macOS：父进程死后子进程被 re-parent，getppid() 必然改变；
    - Windows：无 re-parent 机制（getppid 恒不变），改为探活父进程
      （_win_process_alive：进程已退出但句柄未回收时不算存活，否则
      看门狗会永远等不到"父死"）。不能用 os.kill(pid, 0)——Windows 上
      后者对普通信号会调用 TerminateProcess，等于把父进程直接杀掉。

    供 run_scheduler / run_script_split_worker 等独立进程入口共用。
    """
    if sys.platform == 'win32':
        return not _win_process_alive(initial_ppid)
    return os.getppid() != initial_ppid


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
        return False

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

    # 下载队列消费者：异步消费 download_queue，解耦主循环的分钟级 IO 下载
    task_with_app_download = partial(_run_async_task, process_download_queue)
    logger.info(f'启用下载队列消费者任务（间隔 {DOWNLOAD_POLL_INTERVAL} 秒）')
    scheduler.add_job(
        func=task_with_app_download,
        trigger=IntervalTrigger(seconds=DOWNLOAD_POLL_INTERVAL),
        id='download_queue_worker',
        name=f'Consume download_queue every {DOWNLOAD_POLL_INTERVAL} seconds',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )

    logger.info('启用下载队列健康检查，每 5 分钟执行一次')
    from task.download_queue_health import check_download_queue_health
    scheduler.add_job(
        func=check_download_queue_health,
        trigger=IntervalTrigger(minutes=5),
        id='download_queue_health_check',
        name='Download queue health check every 5 minutes',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # 商业许可证周期续租（仅商业版注册；开源版无商业许可证概念，注册亦被跳过）：
    # scheduler 等非 ASGI 进程的事件循环是短生命周期的，无法常驻后台续租任务，
    # 进程启动时获取的短期许可证租约（约 24h）到期后商业能力全部失效
    # （2026-09-15 生产事故：结果交付链路被卡、任务积压，每天租约到期时刻复发），
    # 必须由本 job 周期触发续租门面。具体续租实现由商业版仓库注册，
    # 主仓门面在社区版为空操作。
    if not Edition.is_community():
        from task.license_rebootstrap_task import rebootstrap_commercial_license
        logger.info(f'启用商业许可证周期重 bootstrap（间隔 {LICENSE_REBOOTSTRAP_INTERVAL_SECONDS} 秒）')
        scheduler.add_job(
            func=rebootstrap_commercial_license,
            trigger=IntervalTrigger(seconds=LICENSE_REBOOTSTRAP_INTERVAL_SECONDS),
            id='commercial_license_rebootstrap',
            name=f'Rebootstrap commercial license every {LICENSE_REBOOTSTRAP_INTERVAL_SECONDS} seconds',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
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

    from task.voice_replace_task import process_voice_replace_jobs
    task_voice_replace = partial(_run_async_task, process_voice_replace_jobs)
    logger.info(
        '启用成片音色替换任务，每%s秒执行一次',
        VoiceReplaceConstants.SCHEDULER_INTERVAL_SECONDS,
    )
    scheduler.add_job(
        func=task_voice_replace,
        trigger=IntervalTrigger(seconds=VoiceReplaceConstants.SCHEDULER_INTERVAL_SECONDS),
        id='process_voice_replace_jobs',
        name=f'Process voice replace jobs every {VoiceReplaceConstants.SCHEDULER_INTERVAL_SECONDS} seconds',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
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
    logger.info('Enable storyboard image batch orchestration task')
    from task.storyboard_image_batch_task import process_storyboard_image_batch_tasks
    task_with_app_storyboard_image_batch = partial(process_storyboard_image_batch_tasks, app=app)

    scheduler.add_job(
        func=task_with_app_storyboard_image_batch,
        trigger=IntervalTrigger(seconds=StoryboardAutoGenerateConstants.BATCH_SCHEDULER_INTERVAL_SECONDS),
        id='process_storyboard_image_batch_tasks',
        name='Process storyboard image batch tasks',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

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

    # 用户模块（接口模块）任务提交/轮询与实现方绑定重载：商业版 enterprise 包提供
    # 调度任务注册（路由受信模型注入等逻辑同侧维护），社区版无此包时跳过。
    try:
        from enterprise.task.user_module_scheduler import register_user_module_scheduler_jobs
        register_user_module_scheduler_jobs(
            scheduler,
            run_async_task=lambda coro_fn: partial(_run_async_task, coro_fn),
        )
    except ImportError:
        logger.info('用户模块调度任务未注册（社区版无 enterprise 包）')
    except Exception:
        logger.exception('用户模块调度任务注册失败')

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

    # 剧本分段拆分任务消费者：单步状态机，每 tick 推进一个任务的一个有限步骤。
    # 见 docs/script/script_parser_incremental_split_design.md §12。
    from config.constant import ScriptSplitConstants
    from task.script_split_task import process_script_split_tasks
    _script_split_interval = ScriptSplitConstants.SCHEDULER_INTERVAL_SECONDS
    # worker_total>0 时切换为多 worker 模式：由 run_prod/run_dev 拉起的 N 个独立
    # worker 进程分片接管，主调度器跳过此 job，避免与 worker 竞争。
    _worker_total = get_dynamic_config_value("script_split", "worker_total", default=0)
    if _worker_total and _worker_total > 0:
        logger.info(
            '剧本分段拆分已切换为 %d 个独立 worker 进程分片接管，主调度器跳过此 job',
            _worker_total,
        )
    else:
        task_with_app_script_split = partial(_run_async_task, process_script_split_tasks)
        logger.info('启用剧本分段拆分任务消费者，每%d秒执行一次', _script_split_interval)
        scheduler.add_job(
            func=task_with_app_script_split,
            trigger=IntervalTrigger(seconds=_script_split_interval),
            id='process_script_split_tasks',
            name=f'Process script split tasks every {_script_split_interval} seconds',
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=30,
        )

    # 月度订阅续期（微信委托代扣·周期扣费：预扣费通知→申请扣款→失败重试→窗口耗尽关单）
    # 内部遵守微信 7:00~22:00 扣费时间窗，窗口外 tick 直接跳过。
    _sub_interval = SubscriptionConstants.SCHEDULER_INTERVAL_MINUTES
    task_with_app_subscription = partial(_run_async_task, process_subscription_renewals)
    logger.info('启用月度订阅续期任务，每%d分钟执行一次', _sub_interval)
    scheduler.add_job(
        func=task_with_app_subscription,
        trigger=IntervalTrigger(minutes=_sub_interval),
        id='process_subscription_renewals',
        name=f'Process subscription renewals every {_sub_interval} minutes',
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    # 启动调度器
    scheduler.start()
    logger.info("定时任务启动成功")
    return True

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
