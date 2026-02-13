"""
跨进程文件锁工具

使用 O_CREAT|O_EXCL 原子创建锁文件实现跨进程互斥，
适用于 gunicorn 多 worker 场景。锁文件内含时间戳用于超时检测。
"""

import os
import time


def try_acquire(lock_path: str, timeout_seconds: int = 120) -> bool:
    """
    尝试获取文件锁（跨进程安全）。

    Args:
        lock_path: 锁文件路径
        timeout_seconds: 锁超时时间（秒），超过此时间视为死锁可强制接管

    Returns:
        True 表示获取成功，False 表示锁被其他进程持有
    """
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(time.time()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        # 锁文件已存在，检查是否超时
        try:
            with open(lock_path, 'r') as f:
                lock_time = float(f.read().strip())
            if time.time() - lock_time > timeout_seconds:
                # 超时，尝试删除并重新获取（只重试一次，避免循环竞争）
                try:
                    os.unlink(lock_path)
                except FileNotFoundError:
                    pass
                try:
                    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, str(time.time()).encode())
                    os.close(fd)
                    return True
                except FileExistsError:
                    return False
            return False
        except Exception:
            return False


def release(lock_path: str):
    """释放文件锁"""
    try:
        os.unlink(lock_path)
    except FileNotFoundError:
        pass
