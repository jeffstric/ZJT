"""Prepare and start the Windows tray launcher with a persistent uv environment.

This module intentionally uses only the Python standard library. ``launcher_me.bat``
runs it with the complete Python distribution bundled in ``bin/python``. It then
lets uv build a relocatable, hash-addressed launcher environment and starts
``launcher.py`` from that stable environment. No Python download is allowed on an
end-user machine.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Iterator, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constant import (  # noqa: E402
    UV_BUNDLED_PYTHON_REQUEST,
    UV_LAUNCHER_BOOTSTRAP_LOCK_TIMEOUT_SECONDS,
    UV_LAUNCHER_DEPENDENCY_SYNC_TIMEOUT_SECONDS,
    UV_LAUNCHER_ENV_CREATE_TIMEOUT_SECONDS,
    UV_LAUNCHER_ENV_SCHEMA_VERSION,
    UV_LAUNCHER_IMPORT_PROBE_TIMEOUT_SECONDS,
    UV_LAUNCHER_PROCESS_PROBE_TIMEOUT_SECONDS,
)


WINDOWS_BOOTSTRAP_MUTEX = "Local\\ZhiJuTong_Uv_Launcher_Bootstrap_v1"
LOGGER = logging.getLogger("zjt.launcher.bootstrap")


class BootstrapError(RuntimeError):
    """A user-facing launcher bootstrap failure."""


def _uv_path(project_root: Path) -> Path:
    candidates = (
        project_root / "bin" / "uv" / "uv.exe",
        project_root / "bin" / "uv" / "uv",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    system_uv = shutil.which("uv")
    if system_uv:
        return Path(system_uv)
    raise BootstrapError("找不到 uv，请确认程序包包含 bin\\uv\\uv.exe")


def launcher_environment_key(requirements_file: Path) -> str:
    """Return a stable key for the launcher dependency/runtime contract."""
    digest = hashlib.sha256()
    digest.update(f"schema={UV_LAUNCHER_ENV_SCHEMA_VERSION}\n".encode("ascii"))
    digest.update(f"python={UV_BUNDLED_PYTHON_REQUEST}\n".encode("ascii"))
    digest.update(f"platform={sys.platform}\n".encode("ascii"))
    digest.update(requirements_file.read_bytes())
    return digest.hexdigest()[:16]


def launcher_environment_dir(project_root: Path, requirements_file: Path) -> Path:
    key = launcher_environment_key(requirements_file)
    return project_root / "bin" / "runtime" / f"launcher-{key}"


def _environment_python(environment_dir: Path, *, windowed: bool = False) -> Path:
    if os.name == "nt":
        executable = "pythonw.exe" if windowed else "python.exe"
        candidate = environment_dir / "Scripts" / executable
        if windowed and not candidate.is_file():
            candidate = environment_dir / "Scripts" / "python.exe"
        return candidate
    return environment_dir / "bin" / "python"


def bundled_python_executable(project_root: Path, *, windowed: bool = False) -> Path:
    """Return the complete, relocatable Python shipped in the application package."""
    install_root = project_root / "bin" / "python"
    if (install_root / "pyvenv.cfg").exists():
        raise BootstrapError(
            "bin\\python 是不可搬迁的虚拟环境，而不是完整 Python。"
            "请重新解压包含内置 Python 的完整程序包。"
        )
    executable_name = "pythonw.exe" if windowed and os.name == "nt" else "python.exe"
    if os.name != "nt":
        executable_name = "python"
    executable = install_root / UV_BUNDLED_PYTHON_REQUEST / executable_name
    if not executable.is_file():
        raise BootstrapError(
            f"程序包缺少内置 Python：{executable}。请重新下载或解压完整程序包。"
        )
    return executable


def _log_process_output(command: Sequence[str], completed: subprocess.CompletedProcess) -> None:
    if completed.stdout:
        for line in completed.stdout.rstrip().splitlines():
            LOGGER.info("uv: %s", line)
    if completed.stderr:
        for line in completed.stderr.rstrip().splitlines():
            LOGGER.warning("uv: %s", line)
    if completed.returncode != 0:
        LOGGER.error("命令失败（退出码 %s）：%s", completed.returncode, " ".join(command))


def _run_checked(command: Sequence[str], *, timeout: int, cwd: Path) -> None:
    LOGGER.info("执行：%s", " ".join(command))
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BootstrapError(f"uv 操作超时（{timeout} 秒）：{command[1]}") from exc
    _log_process_output(command, completed)
    if completed.returncode != 0:
        raise BootstrapError(f"uv 操作失败（退出码 {completed.returncode}）：{command[1]}")


def _probe_environment(environment_dir: Path) -> bool:
    python_executable = _environment_python(environment_dir)
    if not python_executable.is_file():
        return False
    probe = "import PIL, pystray, yaml; print('launcher-runtime-ok')"
    try:
        completed = subprocess.run(
            [str(python_executable), "-X", "utf8", "-c", probe],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=UV_LAUNCHER_IMPORT_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and "launcher-runtime-ok" in completed.stdout


@contextlib.contextmanager
def _windows_bootstrap_lock(timeout_seconds: int) -> Iterator[None]:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = kernel32.CreateMutexW(None, False, WINDOWS_BOOTSTRAP_MUTEX)
    if not handle:
        raise BootstrapError("无法创建启动互斥锁")
    wait_result = kernel32.WaitForSingleObject(handle, int(timeout_seconds * 1000))
    if wait_result not in (0x00000000, 0x00000080):  # WAIT_OBJECT_0 / WAIT_ABANDONED
        kernel32.CloseHandle(handle)
        raise BootstrapError("等待另一个启动器准备环境超时")
    try:
        yield
    finally:
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


@contextlib.contextmanager
def _posix_bootstrap_lock(lock_file: Path, timeout_seconds: int) -> Iterator[None]:
    import fcntl

    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise BootstrapError("等待另一个启动器准备环境超时")
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _bootstrap_lock(runtime_root: Path) -> contextlib.AbstractContextManager:
    if os.name == "nt":
        return _windows_bootstrap_lock(UV_LAUNCHER_BOOTSTRAP_LOCK_TIMEOUT_SECONDS)
    return _posix_bootstrap_lock(
        runtime_root / ".launcher-bootstrap.lock",
        UV_LAUNCHER_BOOTSTRAP_LOCK_TIMEOUT_SECONDS,
    )


def _safe_remove_build_dir(build_dir: Path, runtime_root: Path) -> None:
    try:
        is_scoped_build = (
            build_dir.parent.resolve() == runtime_root.resolve()
            and build_dir.name.startswith(".launcher-build-")
        )
    except OSError:
        is_scoped_build = False
    if is_scoped_build and build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)


def ensure_launcher_environment(
    project_root: Path,
    uv_executable: Path,
    requirements_file: Path,
    bundled_python: Path,
) -> Path:
    """Create and validate the hash-addressed launcher environment."""
    if not requirements_file.is_file():
        raise BootstrapError(f"找不到启动器依赖清单：{requirements_file}")
    if not any(
        line.strip() and not line.lstrip().startswith("#")
        for line in requirements_file.read_text(encoding="utf-8").splitlines()
    ):
        raise BootstrapError(f"启动器依赖清单为空：{requirements_file}")

    runtime_root = project_root / "bin" / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    target_dir = launcher_environment_dir(project_root, requirements_file)
    if _probe_environment(target_dir):
        LOGGER.info("复用 launcher 环境：%s", target_dir)
        return target_dir

    with _bootstrap_lock(runtime_root):
        if _probe_environment(target_dir):
            LOGGER.info("另一个启动进程已准备好 launcher 环境：%s", target_dir)
            return target_dir

        build_dir = runtime_root / f".launcher-build-{os.getpid()}-{time.time_ns()}"
        _safe_remove_build_dir(build_dir, runtime_root)
        try:
            LOGGER.info("正在通过 uv 创建 launcher 环境，请稍候……")
            _run_checked(
                [
                    str(uv_executable),
                    "venv",
                    "--python",
                    str(bundled_python),
                    "--no-python-downloads",
                    "--relocatable",
                    "--link-mode",
                    "copy",
                    str(build_dir),
                ],
                timeout=UV_LAUNCHER_ENV_CREATE_TIMEOUT_SECONDS,
                cwd=project_root,
            )
            build_python = _environment_python(build_dir)
            _run_checked(
                [
                    str(uv_executable),
                    "pip",
                    "install",
                    "--python",
                    str(build_python),
                    "--requirements",
                    str(requirements_file),
                    "--strict",
                    "--compile-bytecode",
                ],
                timeout=UV_LAUNCHER_DEPENDENCY_SYNC_TIMEOUT_SECONDS,
                cwd=project_root,
            )
            if not _probe_environment(build_dir):
                raise BootstrapError("launcher 环境依赖导入验证失败")
            if target_dir.exists():
                if _probe_environment(target_dir):
                    return target_dir
                raise BootstrapError(f"目标 launcher 环境已存在但不可用：{target_dir}")
            os.replace(build_dir, target_dir)
            LOGGER.info("launcher 环境准备完成：%s", target_dir)
            return target_dir
        finally:
            _safe_remove_build_dir(build_dir, runtime_root)


def launch_tray(project_root: Path, environment_dir: Path) -> int:
    launcher_script = project_root / "scripts" / "launchers" / "launcher.py"
    if not launcher_script.is_file():
        raise BootstrapError(f"找不到托盘启动脚本：{launcher_script}")

    python_executable = _environment_python(environment_dir, windowed=True)
    if not python_executable.is_file():
        raise BootstrapError(f"找不到 launcher Python：{python_executable}")

    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    runtime_log_path = logs_dir / "launcher_runtime.log"
    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"

    creation_flags = 0
    popen_kwargs = {}
    if os.name == "nt":
        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    with runtime_log_path.open("a", encoding="utf-8", errors="replace") as runtime_log:
        process = subprocess.Popen(
            [str(python_executable), "-X", "utf8", str(launcher_script)],
            cwd=str(project_root),
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=runtime_log,
            stderr=subprocess.STDOUT,
            close_fds=True,
            creationflags=creation_flags,
            **popen_kwargs,
        )

    try:
        return_code = process.wait(timeout=UV_LAUNCHER_PROCESS_PROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        LOGGER.info("托盘启动器已启动，PID=%s", process.pid)
        return 0

    if return_code == 0:
        # A duplicate launcher shows its own message and exits normally.
        LOGGER.info("托盘启动器已正常退出（可能已有实例在运行）")
        return 0
    raise BootstrapError(
        f"托盘启动器启动后立即退出（退出码 {return_code}），请查看 {runtime_log_path}"
    )


def _configure_logging(project_root: Path) -> None:
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(logs_dir / "launcher_bootstrap.log", encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
        force=True,
    )


def _show_windows_error(message: str) -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(0, message, "智剧通启动失败", 0x10 | 0x40000)
    except Exception:
        pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare and start the ZJT tray launcher")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args(argv)
    project_root = args.project_root.resolve()
    _configure_logging(project_root)

    try:
        uv_executable = _uv_path(project_root)
        bundled_python = bundled_python_executable(project_root)
        requirements_file = project_root / "requirements-launcher.txt"
        environment_dir = ensure_launcher_environment(
            project_root,
            uv_executable,
            requirements_file,
            bundled_python,
        )
        return launch_tray(project_root, environment_dir)
    except Exception as exc:
        LOGGER.exception("启动失败：%s", exc)
        _show_windows_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
