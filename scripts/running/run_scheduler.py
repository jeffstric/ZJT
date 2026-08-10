#!/usr/bin/env python3
"""
定时任务调度器独立进程
用于在 gunicorn 多进程环境下单独运行定时任务
"""
import signal
import sys
import time
import os

# 添加项目根目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from server import app
from task.scheduler import init_scheduler, shutdown_scheduler


def cleanup(signum=None, frame=None):
    """清理并退出"""
    print("[Scheduler] Shutting down...")
    try:
        shutdown_scheduler()
    except Exception as e:
        print(f"[Scheduler] Cleanup error: {e}")
    finally:
        sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    # Mac/Linux 关闭终端窗口时会发送 SIGHUP，需要捕获并清理
    # Windows 不支持 SIGHUP，跳过
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, cleanup)
    
    print("[Scheduler] Starting scheduler...")
    print(f"[Scheduler] PID: {os.getpid()}")

    # 商业许可证：import server 时已 enterprise.register（闩锁打开），
    # 但本进程不跑 uvicorn，FastAPI startup 不会触发 start_runtime。
    # 在此读盘 JWT / 复用 zjt.token 启动进程内 manager，供 quality 拆分等
    # require_commercial_license 使用。不要求用户再输 token，不新建 installation。
    try:
        from config.constant import Edition
        if not Edition.is_community():
            from enterprise.services.license.runtime import (
                bootstrap_commercial_license_runtime_sync,
            )

            # register 已 mark_registration_ready；仍传 True 以幂等打开闩锁。
            # 关闭后台 refresh：本入口用短生命周期 loop，task 无法常驻。
            bootstrap_commercial_license_runtime_sync(
                open_registration_latch=True,
                enable_background_refresh=False,
            )
            print("[Scheduler] Commercial license runtime bootstrapped")
    except Exception as e:
        print(f"[Scheduler] Warning: commercial license bootstrap failed: {e}")
    
    # init_scheduler 内部会检查文件锁
    init_scheduler(app)
    
    # 保持进程运行，并监控 scheduler 健康状态
    from task.scheduler import scheduler as _scheduler
    try:
        while True:
            time.sleep(60)
            # 健康检查：如果 APScheduler 内部线程崩溃，及时退出
            if _scheduler and not _scheduler.running:
                print("[Scheduler] Scheduler stopped unexpectedly, exiting...")
                cleanup()
    except KeyboardInterrupt:
        cleanup()
