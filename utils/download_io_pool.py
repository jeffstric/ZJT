"""
下载 IO 线程池（模块级长寿 executor）

用途：utils/media_cache.py 的 download_and_cache 把同步文件写盘丢到此线程池执行，
避免在 asyncio 事件循环里做阻塞 IO（CLAUDE.md 第1条）。被 download_queue_worker
的并发下载协程共享；await 串行化保证同一文件对象的 open/write/close 顺序访问安全。

⚠️ 红线（CLAUDE.md 第10条）：
- 必须是模块级长寿 executor，禁止用 `with ThreadPoolExecutor()` 上下文管理器
  （with 退出会触发 shutdown(wait=True)，使后续 .result(timeout=) 假超时、调用线程卡死）。
- 调用方每次 run_in_executor 必须用 asyncio.wait_for(..., timeout=DOWNLOAD_WRITE_CHUNK_TIMEOUT)
  包超时（CLAUDE.md 第9条），禁止无超时等待 future。
"""
import concurrent.futures

from config.constant import DOWNLOAD_IO_POOL_MAX_WORKERS

# 模块级长寿线程池：进程存活期间复用，不随单次下载任务销毁
_DOWNLOAD_IO_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=DOWNLOAD_IO_POOL_MAX_WORKERS,
    thread_name_prefix="download-io",
)


def get_download_io_executor() -> concurrent.futures.ThreadPoolExecutor:
    """返回模块级长寿下载 IO 线程池"""
    return _DOWNLOAD_IO_EXECUTOR
