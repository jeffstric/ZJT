#!/usr/bin/env python3
"""
开发环境统一启动器
- 管理 scheduler 子进程（定时任务）
- 使用 uvicorn 单进程运行 Web 服务（支持热重载）
- 父进程退出时自动清理所有子进程
"""
import subprocess
import signal
import sys
import os
import time
import yaml
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
        return config.get("server", {}).get("port", 5178)
    except Exception as e:
        print(f"[Manager] Warning: Failed to read port from config: {e}")
        return 5178


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
    
    # 2. 启动 uvicorn 开发服务器（单进程，支持热重载）
    print(f"[Manager] Starting uvicorn dev server on port {port}...")
    uvicorn_cmd = [
        sys.executable, "-m", "uvicorn", "server:app",
        "--host", "0.0.0.0",
        "--port", port,
        "--reload"
    ]
    uvicorn_proc = subprocess.Popen(uvicorn_cmd, cwd=cwd)
    processes.append(uvicorn_proc)
    
    print("[Manager] All processes started. Press Ctrl+C to stop.")
    print(f"[Manager] Dev server: http://localhost:{port}")
    
    # 监控子进程
    while True:
        for i, proc in enumerate(processes):
            if proc.poll() is not None:
                name = "scheduler" if i == 0 else "uvicorn"
                print(f"[Manager] {name} exited with code {proc.returncode}")
                cleanup()
        time.sleep(1)


if __name__ == "__main__":
    main()
