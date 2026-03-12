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
from config.config_util import get_config_path


# 子进程列表
processes = []


def cleanup(signum=None, frame=None):
    """清理所有子进程"""
    print("\n[Manager] Shutting down all processes...")
    for proc in processes:
        if proc.poll() is None:
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
    # 注册信号处理器
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    
    cwd = os.path.dirname(os.path.abspath(__file__))
    
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
        [sys.executable, "run_scheduler.py"],
        cwd=cwd
    )
    processes.append(scheduler_proc)
    
    # 等待 scheduler 启动
    time.sleep(2)
    
    # 2. 启动 Web 服务进程
    is_windows = platform.system() == "Windows"
    
    if is_windows:
        # Windows 使用 uvicorn（gunicorn 不支持 Windows）
        print(f"[Manager] Starting uvicorn on port {port}...")
        web_cmd = [
            sys.executable, "-m", "uvicorn", "server:app",
            "--host", "0.0.0.0",
            "--port", port,
            "--timeout-keep-alive", "600"
        ]
        web_server_name = "uvicorn"
    else:
        # Linux/macOS 使用 gunicorn（性能更好）
        print(f"[Manager] Starting gunicorn on port {port}...")
        web_cmd = [
            "gunicorn", "server:app",
            "-w", "4",
            "-k", "uvicorn.workers.UvicornWorker",
            "--bind", f"0.0.0.0:{port}",
            "--timeout", "600",
            "--graceful-timeout", "90",
            "--access-logfile", "access.log",
            "--error-logfile", "error.log"
        ]
        web_server_name = "gunicorn"
    
    web_proc = subprocess.Popen(web_cmd, cwd=cwd)
    processes.append(web_proc)
    
    print("[Manager] All processes started. Press Ctrl+C to stop.")
    
    # 监控子进程
    while True:
        for i, proc in enumerate(processes):
            if proc.poll() is not None:
                name = "scheduler" if i == 0 else web_server_name
                print(f"[Manager] {name} exited with code {proc.returncode}")
                cleanup()
        time.sleep(1)


if __name__ == "__main__":
    main()
