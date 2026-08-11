#!/usr/bin/env python3
"""
生产环境统一启动器
- 管理 scheduler 子进程（定时任务）
- 管理 gunicorn/uvicorn 子进程（Web 服务）
- 父进程退出时自动清理所有子进程
- Windows 系统使用 uvicorn，Linux/macOS 使用 gunicorn
"""
import os
import subprocess
import signal
import sys
import time
import yaml
import platform
import argparse

# 添加项目根目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from config.config_util import get_config_path


# 子进程列表
processes = []
# script split worker 子进程（独立列表，单 worker 崩溃不触发共存亡，但随 cleanup 一起清理）
worker_processes = []


def cleanup(signum=None, frame=None):
    """清理所有子进程"""
    print("\n[Manager] Shutting down all processes...")
    for proc in processes + worker_processes:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    print("[Manager] All processes stopped.")
    sys.exit(0)


def get_port_from_config():
    """从配置文件读取端口号"""
    try:
        config_file = get_config_path()
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config.get("server", {}).get("port", 8000)
    except Exception as e:
        print(f"[Manager] Warning: Failed to read port from config: {e}")
        return 8000


def main():
    # Direct execution defaults to prod, while an explicit launcher-selected
    # environment must be preserved for configuration isolation.
    os.environ.setdefault('comfyui_env', 'prod')
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='生产环境统一启动器')
    parser.add_argument(
        '-w', '--workers',
        type=int,
        default=4,
        help='Gunicorn worker 进程数 (默认: 4, 仅适用于 Linux)'
    )
    args = parser.parse_args()
    
    # 注册信号处理器
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    # Mac/Linux 关闭终端窗口时会发送 SIGHUP，需要捕获并清理子进程
    # Windows 不支持 SIGHUP 信号
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, cleanup)
    
    # 使用项目根目录作为工作目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    cwd = os.path.dirname(os.path.dirname(current_dir))
    
    # 在启动服务之前先执行数据库迁移
    from model.migration import get_alembic_config, run_migrations
    alembic_config = get_alembic_config()
    if alembic_config.get('auto_migrate', False):
        print("[Manager] Running database migrations...")
        try:
            run_migrations()
            print("[Manager] Database migrations completed.")
        except Exception as e:
            print(f"[Manager] Database migration failed: {e}")
            print("[Manager] Cannot start server with failed migrations. Exiting...")
            sys.exit(1)
    
    # 优先使用环境变量 PORT，否则从配置文件读取
    port = os.environ.get("PORT")
    if port is None:
        port = get_port_from_config()
    port = str(port)
    
    # 1. 启动定时任务进程
    print("[Manager] Starting scheduler process...")
    scheduler_proc = subprocess.Popen(
        [sys.executable, "scripts/running/run_scheduler.py"],
        cwd=cwd
    )
    processes.append(scheduler_proc)

    # 等待 scheduler 启动
    time.sleep(2)

    # 1.5 启动剧本分段拆分独立 worker 进程（分片消费 script_split_task）
    #     worker_total>0 时由 N 个 worker 进程分片接管，主调度器会自动跳过该 job。
    #     worker 单个崩溃不拖垮核心服务（监控循环仅对 processes 共存亡），
    #     但随 cleanup 一起 terminate（重启服务自动清理，避免重复建进程）。
    try:
        from config.config_util import get_dynamic_config_value
        worker_total = int(get_dynamic_config_value("script_split", "worker_total", default=0) or 0)
    except Exception as e:
        print(f"[Manager] Warning: Failed to read script_split.worker_total: {e}")
        worker_total = 0
    if worker_total > 0:
        print(f"[Manager] Starting {worker_total} script split worker processes...")
        for idx in range(worker_total):
            wp = subprocess.Popen(
                [sys.executable, "scripts/running/run_script_split_worker.py",
                 str(idx), str(worker_total)],
                cwd=cwd
            )
            worker_processes.append(wp)
            time.sleep(0.5)  # 错开启动，避免瞬时 DB 连接尖峰

    # 2. 启动 Web 服务进程
    system = platform.system()
    
    if system == "Windows" or system == "Darwin":
        # Windows 和 macOS 使用 uvicorn
        # macOS 使用 uvicorn 避免 gunicorn fork 导致的 objc 崩溃问题
        print(f"[Manager] Starting uvicorn on port {port}...")
        web_cmd = [
            sys.executable, "-m", "uvicorn", "server:app",
            "--host", "0.0.0.0",
            "--port", port,
            "--timeout-keep-alive", "600"
        ]
        web_server_name = "uvicorn"
    else:
        # Linux 使用 gunicorn（性能更好）
        print(f"[Manager] Starting gunicorn with {args.workers} workers on port {port}...")
        web_cmd = [
            sys.executable, "-m", "gunicorn", "server:app",
            "-w", str(args.workers),
            "-k", "uvicorn.workers.UvicornWorker",
            "--bind", f"0.0.0.0:{port}",
            "--timeout", "600",
            "--graceful-timeout", "90",
            "--access-logfile", "access.log",
            "--error-logfile", "error.log"
        ]
        web_server_name = "gunicorn"
    
    # macOS 需要设置环境变量避免 fork 崩溃
    env = os.environ.copy()
    if system == "Darwin":
        env['OBJC_DISABLE_INITIALIZE_FORK_SAFETY'] = 'YES'
    
    web_proc = subprocess.Popen(web_cmd, cwd=cwd, env=env)
    processes.append(web_proc)
    
    print("[Manager] All processes started. Press Ctrl+C to stop.")
    
    # 监控子进程：核心进程（scheduler/web）任一退出则 cleanup 全部；
    # worker 进程单独监控，单个崩溃仅告警不拖垮核心服务。
    while True:
        for i, proc in enumerate(processes):
            if proc.poll() is not None:
                name = "scheduler" if i == 0 else web_server_name
                print(f"[Manager] {name} exited with code {proc.returncode}")
                cleanup()
        for i, wproc in enumerate(worker_processes):
            if wproc is not None and wproc.poll() is not None:
                print(f"[Manager] WARNING: script split worker[{i}] exited with code {wproc.returncode}, "
                      f"core service keeps running")
                worker_processes[i] = None  # 标记已退出，避免重复告警
        time.sleep(1)


if __name__ == "__main__":
    main()
