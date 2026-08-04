import importlib.util
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SCRIPT = REPO_ROOT / "scripts" / "package.py"


def load_package_module():
    spec = importlib.util.spec_from_file_location("zjt_package_test", PACKAGE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_windows_package_bundles_and_probes_python_with_uv(tmp_path, monkeypatch):
    package = load_package_module()
    package_root = tmp_path / "package"
    bin_dir = package_root / "bin"
    uv_executable = bin_dir / "uv" / "uv.exe"
    uv_executable.parent.mkdir(parents=True)
    uv_executable.touch()
    python_request = "cpython-3.10.20-windows-x86_64-none"
    commands = []

    monkeypatch.setattr(package, "CODE_PATH", tmp_path / "source")
    monkeypatch.setattr(package, "NAS_PATH", tmp_path / "nas")

    def fake_run(command, **kwargs):
        commands.append(list(command))
        if command[1:3] == ["python", "install"]:
            python_executable = bin_dir / "python" / python_request / "python.exe"
            python_executable.parent.mkdir(parents=True)
            python_executable.touch()
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "bundled-python-ok\n", "")

    monkeypatch.setattr(package.subprocess, "run", fake_run)

    package.copy_managed_python(
        bin_dir,
        {
            "uv_dst": "uv.exe",
            "python_request": python_request,
            "python_src": "python-windows",
        },
        "Windows",
    )

    assert len(commands) == 2
    assert commands[0][0] == str(uv_executable)
    assert commands[0][1:3] == ["python", "install"]
    assert "--install-dir" in commands[0]
    assert "--no-bin" in commands[0]
    assert "--no-registry" in commands[0]
    assert commands[0][-1] == python_request
    assert commands[1][0].endswith(f"{python_request}\\python.exe")


def test_non_windows_package_skips_bundled_python(tmp_path, monkeypatch):
    package = load_package_module()
    monkeypatch.setattr(
        package.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("uv should not run")),
    )

    package.copy_managed_python(tmp_path / "bin", {"uv_dst": "uv"}, "macOS-x86")
