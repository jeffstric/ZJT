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


def cleanup(signum=None, frame=None):
    """清理并退出"""
    print("[Scheduler] Shutting down...")
    try:
        from task.scheduler import shutdown_scheduler
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

    # 防孤儿看门狗必须在一切耗时步骤之前安装（from server import app 可达数秒、
    # 许可证 bootstrap / init_scheduler 内还有进程池 fork）：PDEATHSIG 不补发
    # 安装前已发生的父死亡；且父死后本进程被 re-parent 到 init，getppid() 恒为 1，
    # 之后拍到的 initial_ppid 与看门狗轮询值都是 1，永不触发 → 永久孤儿持锁
    # （生产曾积累 31 个调度器进程）。
    if sys.platform.startswith('linux'):
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG = 1
    initial_ppid = os.getppid()
    if initial_ppid == 1 and sys.platform != 'win32':
        # fork/exec 间隙父进程已死（PDEATHSIG 尚未安装、无法补发），立即退出防孤儿。
        # 本进程仅由 run_prod/run_dev 拉起（父为 manager），ppid==1 只意味着已成孤儿。
        print("[Scheduler] Parent process died before watchdog install, exiting.")
        sys.exit(0)

    print("[Scheduler] Starting scheduler...")
    print(f"[Scheduler] PID: {os.getpid()}")

    # server / task.scheduler 的 import 各自可达数秒，必须在看门狗安装之后
    # 注意：scheduler 实例必须经模块属性动态访问（init_scheduler 内部会
    # global 重建 BackgroundScheduler，提前 from-import 会固化旧的 None 引用）
    from server import app
    from task.scheduler import init_scheduler, parent_process_dead
    import task.scheduler as scheduler_module

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

    # 锁被其他实例持有时不能退出进程：run_prod 把 scheduler 退出视作核心进程
    # 死亡并 cleanup 拆掉整栈（含 Web）。锁冲突只应拒绝本进程的调度职能——
    # 保活空转 + 周期重试，待持有者退出（flock 随进程死亡由内核释放）自动接管。
    # 场景：run_prod 被 SIGKILL 后立刻重启，旧 scheduler 处理 SIGTERM 释放锁前，
    # 新 scheduler 会短暂抢锁失败；dev+prod 双开时第二套持续空转保活。
    while not init_scheduler(app):
        print("[Scheduler] Another scheduler instance holds the lock. "
              "Staying alive (web unaffected); retrying in 30s...")
        time.sleep(30)

    try:
        while True:
            time.sleep(60)
            # 父进程已死亡（被 SIGKILL/断电强杀）→ 本进程成为孤儿，立即退出
            if parent_process_dead(initial_ppid):
                print("[Scheduler] Parent process died, exiting to avoid becoming an orphan...")
                cleanup()
            # 健康检查：如果 APScheduler 内部线程崩溃，及时退出
            _scheduler = scheduler_module.scheduler
            if _scheduler and not _scheduler.running:
                print("[Scheduler] Scheduler stopped unexpectedly, exiting...")
                cleanup()
    except KeyboardInterrupt:
        cleanup()
