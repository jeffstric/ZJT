"""
下载 IO 线程池（模块级长寿 executor，fork 安全）

用途：utils/media_cache.py 的 download_and_cache 把同步文件写盘丢到此线程池执行，
避免在 asyncio 事件循环里做阻塞 IO（CLAUDE.md 第1条）。被 download_queue_worker
的并发下载协程共享；await 串行化保证同一文件对象的 open/write/close 顺序访问安全。

⚠️ 红线（CLAUDE.md 第10条）：
- 必须是模块级长寿 executor，禁止用 `with ThreadPoolExecutor()` 上下文管理器
  （with 退出会触发 shutdown(wait=True)，使后续 .result(timeout=) 假超时、调用线程卡死）。
- 调用方每次 run_in_executor 必须用 asyncio.wait_for(..., timeout=DOWNLOAD_WRITE_CHUNK_TIMEOUT)
  包超时（CLAUDE.md 第9条），禁止无超时等待 future。

⚠️ fork 安全（pid 守卫，与 model/database.py 的 _pool_pid 同构）：
- fork 只复制调用线程，不复制线程池的工作线程：子进程继承的 ThreadPoolExecutor
  带着父进程的"假空闲信号量 token + _threads 死对象"，首个 submit 消费假 token
  后跳过建线程，任务入队永不被执行，上层 wait_for 只能假超时（事故 2026-10-18
  10:03 zjt_trial task 1186：seedream 下载写盘连续精确 30s 超时，网络/磁盘实测
  均正常）。sync worker 默认已切 spawn（见 docs/backend/sync_worker_spawn_
  cutover.md），本守卫为回退 fork 启动方式时的双保险。
"""
import concurrent.futures
import os
import threading

from config.constant import DOWNLOAD_IO_POOL_MAX_WORKERS

# 模块级长寿线程池：进程存活期间复用，不随单次下载任务销毁。
# 延迟到首次 get_download_io_executor() 时创建：避免父进程 import 即建池，
# 把"用过"的池簿记快照给 fork 子进程（见上方 fork 安全说明）。
_DOWNLOAD_IO_EXECUTOR: concurrent.futures.ThreadPoolExecutor = None  # type: ignore[assignment]
_DOWNLOAD_IO_EXECUTOR_PID = None
_DOWNLOAD_IO_LOCK = threading.Lock()


def _create_download_io_executor() -> concurrent.futures.ThreadPoolExecutor:
    return concurrent.futures.ThreadPoolExecutor(
        max_workers=DOWNLOAD_IO_POOL_MAX_WORKERS,
        thread_name_prefix="download-io",
    )


def get_download_io_executor() -> concurrent.futures.ThreadPoolExecutor:
    """返回当前进程的下载 IO 线程池（fork 漂移时重建）。

    pid 与创建时不一致（fork 出的子进程首次调用）→ 丢弃继承的失效池并新建：
    继承池的空闲 token/线程簿记对子进程全是假值，任何 submit 都会假超时。
    旧池直接丢弃引用不 shutdown——子进程内其线程本就不存在，无资源可回收。
    """
    global _DOWNLOAD_IO_EXECUTOR, _DOWNLOAD_IO_EXECUTOR_PID
    pid = os.getpid()
    if _DOWNLOAD_IO_EXECUTOR is not None and _DOWNLOAD_IO_EXECUTOR_PID == pid:
        return _DOWNLOAD_IO_EXECUTOR
    with _DOWNLOAD_IO_LOCK:
        if _DOWNLOAD_IO_EXECUTOR is None or _DOWNLOAD_IO_EXECUTOR_PID != pid:
            _DOWNLOAD_IO_EXECUTOR = _create_download_io_executor()
            _DOWNLOAD_IO_EXECUTOR_PID = pid
    return _DOWNLOAD_IO_EXECUTOR
