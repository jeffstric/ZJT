#!/usr/bin/env python3
"""
定时任务调度器独立进程
用于在 gunicorn 多进程环境下单独运行定时任务
"""
import signal
import sys
import time
import os

from server import app
from task.scheduler import init_scheduler, shutdown_scheduler


def cleanup(signum=None, frame=None):
    """清理并退出"""
    print("[Scheduler] Shutting down...")
    shutdown_scheduler()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    
    print("[Scheduler] Starting scheduler...")
    print(f"[Scheduler] PID: {os.getpid()}")
    
    # init_scheduler 内部会检查文件锁
    init_scheduler(app)
    
    # 保持进程运行
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        cleanup()
