#!/usr/bin/env python3
"""
剧本分段拆分独立 worker 进程（分片消费）。

只消费 script_split_task 队列中 id MOD total = index 的任务，不启动完整 APScheduler。
多个 worker 进程分片互不重叠，任务领取由 claim_next_task 的 DB 行锁（FOR UPDATE）
+ 租约双重保证不会重复消费。

由 run_prod.py / run_dev.py 在 worker_total>0 时统一拉起（index 0..N-1），
随主进程 cleanup 自动清理；也可手动单独启动用于调试。

用法：
    python scripts/running/run_script_split_worker.py <index> <total>
      index: 本进程分片下标（0-based，必须满足 0 <= index < total）
      total:  总进程数（必须与 config script_split.worker_total 一致）

文件锁：每个 index 占用 <root>/script_split_worker_<index>.lock，防止同 index
重复启动。进程被强制 kill 后，OS 级锁（msvcrt/fcntl）会自动释放；残留的锁文件
会在下次启动时被无害截断覆盖（与 scheduler.lock 同机制）。
"""
import argparse
import asyncio
import logging
import os
import signal
import sys
import time

# 添加项目根目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

# 日志：import 时自动配置 root logger 写入 logs/app.YYYY-MM-DD.log + 控制台
import utils.logger_config  # noqa: F401

logger = logging.getLogger(__name__)

# 本 worker 的 per-index 文件锁句柄与路径
_lock_fd = None
_LOCK_FILE = None


def _is_stale_lock(lock_file):
    """检查锁文件是否来自已死亡的进程（复用 scheduler.py 同款逻辑）。"""
    if not lock_file or not os.path.exists(lock_file):
        return False
    try:
        with open(lock_file, 'r') as f:
            pid_str = f.read().strip()
        if not pid_str:
            # 空文件 = 锁写入失败残留
            return True
        pid = int(pid_str)
        if sys.platform == 'win32':
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
            if handle:
                kernel32.CloseHandle(handle)
                return False
            return True
        else:
            try:
                os.kill(pid, 0)
                return False  # 进程存活，锁有效
            except (ProcessLookupError, PermissionError):
                return True  # 进程已死，锁无效
    except (ValueError, OSError):
        return True  # 文件内容异常，视为残留


def _force_acquire_lock(lock_file):
    """强制获取锁（清除残留锁后重新获取）。"""
    global _lock_fd
    if os.path.exists(lock_file):
        os.remove(lock_file)
    _lock_fd = open(lock_file, 'w')
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
    logger.info("worker lock force-acquired after clearing stale lock: %s", lock_file)


def _acquire_worker_lock(worker_index):
    """获取本 worker index 的文件锁，防止同 index 重复启动。"""
    global _lock_fd, _LOCK_FILE
    _LOCK_FILE = os.path.join(project_root, f"script_split_worker_{worker_index}.lock")
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
        logger.info("worker lock acquired: %s (PID %s)", _LOCK_FILE, os.getpid())
        return True
    except (IOError, OSError):
        _lock_fd.close()
        _lock_fd = None
        if _is_stale_lock(_LOCK_FILE):
            logger.warning("detected stale worker lock, clearing and retrying: %s", _LOCK_FILE)
            _force_acquire_lock(_LOCK_FILE)
            return True
        logger.error("worker index %d already running (lock held): %s", worker_index, _LOCK_FILE)
        return False


def _release_worker_lock():
    """释放本 worker 的文件锁。"""
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
            logger.info("worker lock released: %s", _LOCK_FILE)
        except Exception as e:
            logger.error("error releasing worker lock: %s", e)


def cleanup(signum=None, frame=None):
    """清理并退出。"""
    print(f"[ScriptSplitWorker] Shutting down (index={WORKER_INDEX})...")
    _release_worker_lock()
    sys.exit(0)


def _run_one_tick(coro_func):
    """跑一次单步推进：新建事件循环执行传入的协程函数。

    每次 tick 用独立事件循环（与 scheduler._run_async_task 同款），不复用，
    避免 LLM 客户端连接等资源跨 tick 泄漏。
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(coro_func())
    finally:
        loop.close()


# 模块级，供 cleanup 日志引用
WORKER_INDEX = 0
WORKER_TOTAL = 0


def main():
    global WORKER_INDEX, WORKER_TOTAL

    parser = argparse.ArgumentParser(description='剧本分段拆分独立 worker 进程')
    parser.add_argument('index', type=int, help='本进程分片下标（0-based）')
    parser.add_argument('total', type=int, help='总进程数')
    args = parser.parse_args()

    if args.total <= 0:
        print(f"[ERROR] total 必须 > 0，收到 {args.total}")
        sys.exit(2)
    if args.index < 0 or args.index >= args.total:
        print(f"[ERROR] index 必须满足 0 <= index < total，收到 index={args.index} total={args.total}")
        sys.exit(2)

    global WORKER_INDEX, WORKER_TOTAL
    WORKER_INDEX = args.index
    WORKER_TOTAL = args.total

    # 文件锁防同 index 重复启动
    if not _acquire_worker_lock(WORKER_INDEX):
        sys.exit(3)

    # 注入分片参数：claim_next_task 读取这两个类属性做 id MOD N = index 过滤
    from config.constant import ScriptSplitConstants
    ScriptSplitConstants.WORKER_TOTAL = WORKER_TOTAL
    ScriptSplitConstants.WORKER_INDEX = WORKER_INDEX

    # 独立 worker 不 import server：无 enterprise.register / FastAPI lifespan。
    # 注入进程级 Provider + 许可证 runtime，否则 quality 拆分会报
    # 「许可证尚未启动」，且相关门面回落社区实现。
    # 复用 Web 已落盘的 installation_id + JWT + zjt.token，不要求再输 token。
    try:
        from config.constant import Edition
        if not Edition.is_community():
            import enterprise

            enterprise.bootstrap_background_process(
                enable_background_refresh=False,
                include_failure_retry=False,
                include_marketing_tools=False,
            )
            logger.info(
                "script split worker enterprise background bootstrap done "
                "(index=%d)",
                WORKER_INDEX,
            )
    except Exception:
        logger.exception(
            "script split worker enterprise bootstrap failed "
            "(index=%d)；quality 模式拆分可能不可用",
            WORKER_INDEX,
        )

    # 延迟 import，确保分片常量先注入（process_script_split_tasks 内部 claim 时读取）
    from task.script_split_task import process_script_split_tasks

    # 信号处理
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, cleanup)

    interval = ScriptSplitConstants.SCHEDULER_INTERVAL_SECONDS
    logger.info(
        "script split worker 启动：index=%d total=%d (id%%%d=%d)，tick间隔=%ds，PID=%s",
        WORKER_INDEX, WORKER_TOTAL, WORKER_TOTAL, WORKER_INDEX, interval, os.getpid(),
    )

    # 主循环：每 tick 推进一个任务的一个步骤，单次异常不拖垮进程
    try:
        while True:
            try:
                _run_one_tick(process_script_split_tasks)
            except Exception:
                # process_script_split_tasks 内部已有完整异常处理并写库，
                # 这里兜底防止单次未知异常导致 worker 整体退出。
                logger.exception("worker tick 未捕获异常，跳过本轮")
            time.sleep(interval)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
