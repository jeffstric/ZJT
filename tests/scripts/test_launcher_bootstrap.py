import contextlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_PATH = REPO_ROOT / "scripts" / "launchers" / "bootstrap.py"


def load_bootstrap_module():
    spec = importlib.util.spec_from_file_location("zjt_launcher_bootstrap_test", BOOTSTRAP_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_launcher_environment_key_changes_with_requirements_content(tmp_path):
    bootstrap = load_bootstrap_module()
    requirements = tmp_path / "requirements-launcher.txt"
    requirements.write_text("pystray==0.19.5\n", encoding="utf-8")
    first = bootstrap.launcher_environment_key(requirements)

    requirements.write_text("pystray==0.19.6\n", encoding="utf-8")
    second = bootstrap.launcher_environment_key(requirements)

    assert len(first) == 16
    assert first != second


def test_empty_launcher_requirements_are_rejected(tmp_path):
    bootstrap = load_bootstrap_module()
    requirements = tmp_path / "requirements-launcher.txt"
    requirements.write_text("# comments only\n\n", encoding="utf-8")

    with pytest.raises(bootstrap.BootstrapError, match="依赖清单为空"):
        bootstrap.ensure_launcher_environment(
            tmp_path,
            tmp_path / "uv.exe",
            requirements,
            tmp_path / "python.exe",
        )


def test_existing_valid_environment_is_reused(tmp_path, monkeypatch):
    bootstrap = load_bootstrap_module()
    requirements = tmp_path / "requirements-launcher.txt"
    requirements.write_text("pystray==0.19.5\n", encoding="utf-8")
    target = bootstrap.launcher_environment_dir(tmp_path, requirements)
    target.mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "_probe_environment", lambda path: path == target)

    def unexpected_run(*args, **kwargs):
        raise AssertionError("uv should not run for a valid hash-addressed environment")

    monkeypatch.setattr(bootstrap, "_run_checked", unexpected_run)

    bundled_python = tmp_path / "bin" / "python" / "python.exe"
    result = bootstrap.ensure_launcher_environment(
        tmp_path,
        tmp_path / "uv.exe",
        requirements,
        bundled_python,
    )

    assert result == target


def test_environment_is_built_with_uv_and_atomically_published(tmp_path, monkeypatch):
    bootstrap = load_bootstrap_module()
    requirements = tmp_path / "requirements-launcher.txt"
    requirements.write_text("pystray==0.19.5\n", encoding="utf-8")
    uv_executable = tmp_path / "bin" / "uv" / "uv.exe"
    uv_executable.parent.mkdir(parents=True)
    uv_executable.touch()
    bundled_python = tmp_path / "bin" / "python" / "cpython" / "python.exe"
    bundled_python.parent.mkdir(parents=True)
    bundled_python.touch()
    commands = []

    monkeypatch.setattr(
        bootstrap,
        "_bootstrap_lock",
        lambda runtime_root: contextlib.nullcontext(),
    )

    def fake_run(command, *, timeout, cwd):
        commands.append(list(command))
        if command[1] == "venv":
            environment_dir = Path(command[-1])
            scripts_dir = environment_dir / "Scripts"
            scripts_dir.mkdir(parents=True)
            (scripts_dir / "python.exe").touch()
            (scripts_dir / "pythonw.exe").touch()

    monkeypatch.setattr(bootstrap, "_run_checked", fake_run)
    monkeypatch.setattr(
        bootstrap,
        "_probe_environment",
        lambda path: (path / "Scripts" / "python.exe").is_file(),
    )

    result = bootstrap.ensure_launcher_environment(
        tmp_path,
        uv_executable,
        requirements,
        bundled_python,
    )

    assert result.is_dir()
    assert (result / "Scripts" / "pythonw.exe").is_file()
    assert [command[1] for command in commands] == ["venv", "pip"]
    assert str(bundled_python) in commands[0]
    assert "--managed-python" not in commands[0]
    assert "--no-python-downloads" in commands[0]
    assert "--relocatable" in commands[0]
    assert "--link-mode" in commands[0]
    assert "--requirements" in commands[1]
    assert not list((tmp_path / "bin" / "runtime").glob(".launcher-build-*"))


def test_launch_tray_uses_persistent_pythonw_not_uv(tmp_path, monkeypatch):
    bootstrap = load_bootstrap_module()
    launcher_script = tmp_path / "scripts" / "launchers" / "launcher.py"
    launcher_script.parent.mkdir(parents=True)
    launcher_script.touch()
    environment_dir = tmp_path / "bin" / "runtime" / "launcher-test"
    scripts_dir = environment_dir / "Scripts"
    scripts_dir.mkdir(parents=True)
    pythonw = scripts_dir / "pythonw.exe"
    pythonw.touch()
    captured = {}

    class FakeProcess:
        pid = 12345

        def wait(self, timeout):
            captured["timeout"] = timeout
            raise subprocess.TimeoutExpired("launcher", timeout)

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(bootstrap.subprocess, "Popen", fake_popen)

    assert bootstrap.launch_tray(tmp_path, environment_dir) == 0
    assert Path(captured["command"][0]) == pythonw
    assert all("uv" not in str(part).lower() for part in captured["command"])
    assert captured["timeout"] == bootstrap.UV_LAUNCHER_PROCESS_PROBE_TIMEOUT_SECONDS


def test_windows_batch_uses_bootstrap_without_temporary_dependency_overlay():
    launcher_batch = (REPO_ROOT / "launcher_me.bat").read_text(encoding="utf-8")
    start_batch = (REPO_ROOT / "start.bat").read_text(encoding="utf-8")
    start_windows = (REPO_ROOT / "scripts" / "launchers" / "start_windows.py").read_text(
        encoding="utf-8"
    )

    assert "scripts\\launchers\\bootstrap.py" in launcher_batch
    assert "UV_PYTHON_DOWNLOADS=never" in launcher_batch
    assert "bin\\uv-python" not in launcher_batch
    assert "!BUNDLED_PYTHON!" in launcher_batch
    assert "--with-requirements requirements.txt scripts\\launchers\\launcher.py" not in launcher_batch
    assert "timeout /t" not in launcher_batch.lower()
    assert "cache clean litellm" not in start_batch.lower()
    assert "install_python.ps1" not in start_batch
    assert "UV_PYTHON_DOWNLOADS=never" in start_batch
    assert "--no-python-downloads" in start_batch
    assert "bin\\uv-python" not in start_batch
    assert 'taskkill /f /im uv.exe' not in start_batch.lower()
    assert '"--no-python-downloads"' in start_windows
    assert "UV_BUNDLED_PYTHON_REQUEST" in start_windows
    assert "UV_PYTHON_INSTALL_MIRROR" not in start_windows


def test_bundled_python_rejects_a_virtualenv_at_install_root(tmp_path):
    bootstrap = load_bootstrap_module()
    install_root = tmp_path / "bin" / "python"
    install_root.mkdir(parents=True)
    (install_root / "pyvenv.cfg").write_text("home = C:/missing", encoding="utf-8")

    with pytest.raises(bootstrap.BootstrapError, match="不可搬迁"):
        bootstrap.bundled_python_executable(tmp_path)


def test_health_probe_is_async_and_has_launcher_identity():
    import ast

    system_api = (REPO_ROOT / "api" / "system.py").read_text(encoding="utf-8")
    tree = ast.parse(system_api)
    health_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and any(
            isinstance(decorator, ast.Call)
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
            and decorator.args[0].value == "/health"
            for decorator in node.decorator_list
        )
    )

    assert any(
        isinstance(decorator, ast.Call)
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
        and decorator.args[0].value == "/health"
        for decorator in health_function.decorator_list
    )
    assert '"app": "ZJT"' in system_api
