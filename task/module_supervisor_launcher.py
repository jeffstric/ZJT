"""用户模块 Supervisor 子进程启动器（由主仓 scripts/running/run_prod.py 调用）。

安全设计沿用 docs/backend/user_modules.md（原 enterprise/doc/user_modules_review.md
S1）：Supervisor 是唯一管理版本化 Runner 的进程，核心 Web 进程只经固定网关访问它。
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path


def _wait_for_module_supervisor(port: int, token: str, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            from urllib.request import Request, urlopen

            request = Request(url, headers={"X-Module-Token": token})
            with urlopen(request, timeout=0.5) as response:
                if response.status != 200:
                    raise OSError(f"unexpected status {response.status}")
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start_module_supervisor(cwd: str, find_free_port) -> subprocess.Popen | None:
    """拉起一个用户模块 Supervisor 子进程并等待健康检查就绪。

    每次调用重新分配端口和 token，保证重启后旧连接不会误连到新实例。
    成功返回 Popen 进程对象；启动失败（超时/立即崩溃）清理后返回 None。
    """
    from config.constant import (
        USER_MODULE_SUPERVISOR_PORT_ENV_NAME,
        USER_MODULE_SUPERVISOR_STARTUP_TIMEOUT_SECONDS,
        USER_MODULE_SUPERVISOR_TOKEN_ENV_NAME,
        USER_MODULE_SUPERVISOR_URL_ENV_NAME,
    )

    supervisor_port = find_free_port()
    supervisor_token = secrets.token_urlsafe(32)
    os.environ[USER_MODULE_SUPERVISOR_PORT_ENV_NAME] = str(supervisor_port)
    os.environ[USER_MODULE_SUPERVISOR_TOKEN_ENV_NAME] = supervisor_token
    os.environ[USER_MODULE_SUPERVISOR_URL_ENV_NAME] = f"http://127.0.0.1:{supervisor_port}"
    print(f"[Manager] Starting module supervisor on 127.0.0.1:{supervisor_port}...")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "module_runtime.supervisor",
            "--port",
            str(supervisor_port),
        ],
        cwd=cwd,
        env=os.environ.copy(),
    )
    if not _wait_for_module_supervisor(
        supervisor_port,
        supervisor_token,
        USER_MODULE_SUPERVISOR_STARTUP_TIMEOUT_SECONDS,
    ):
        print("[Manager] WARNING: module supervisor startup timed out")
        # 清理 URL/TOKEN 环境变量，让 web worker 知道 supervisor 不可用
        os.environ.pop(USER_MODULE_SUPERVISOR_URL_ENV_NAME, None)
        os.environ.pop(USER_MODULE_SUPERVISOR_TOKEN_ENV_NAME, None)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        return None
    return proc


__all__ = ["start_module_supervisor"]
