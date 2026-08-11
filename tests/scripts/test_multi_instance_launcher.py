from pathlib import Path
import sys
import types
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_DIR = REPO_ROOT / "scripts" / "launchers"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(LAUNCHER_DIR))

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    connector_module = types.ModuleType("mysql.connector")
    connector_module.Error = Exception
    mysql_module.connector = connector_module
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = connector_module

from scripts.launchers import pid_manager
from scripts.launchers import start_windows


class _DummyLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _FakeProcess:
    def __init__(self, pid=12345, returncode=None):
        self.pid = pid
        self.returncode = returncode

    def poll(self):
        return self.returncode


def test_pid_files_are_isolated_by_project_directory(tmp_path):
    first = tmp_path / "instance-a"
    second = tmp_path / "instance-b"

    first_pid_file = Path(pid_manager.get_pid_file_path(first))
    second_pid_file = Path(pid_manager.get_pid_file_path(second))

    assert first_pid_file != second_pid_file
    assert first_pid_file == first / "data" / "runtime" / "launcher_pids.json"
    assert second_pid_file == second / "data" / "runtime" / "launcher_pids.json"


def test_mysql_port_conflict_fails_instead_of_attaching_to_foreign_process():
    paths = {"mysqld_exe": "mysqld.exe", "mysql_ini": "my.ini"}
    with (
        mock.patch.object(start_windows, "check_mysql_path", return_value=(True, paths)),
        mock.patch.object(start_windows, "update_mysql_ini_paths", return_value=(True, "ok")),
        mock.patch.object(start_windows, "get_mysql_port", return_value=13306),
        mock.patch.object(start_windows, "check_mysql_data_dir", return_value=False),
        mock.patch.object(start_windows, "get_mysql_startup_lock", return_value=_DummyLock()),
        mock.patch.object(start_windows, "check_port_in_use", return_value=True),
        mock.patch.object(start_windows.subprocess, "Popen") as popen,
    ):
        success, message, first_init = start_windows.start_mysql_service({})

    assert success is False
    assert first_init is False
    assert "13306" in message
    assert "独立" in message
    popen.assert_not_called()
    assert start_windows.mysql_process_owned is False


def test_cleanup_never_shuts_down_unowned_mysql(tmp_path):
    start_windows.mysql_process = _FakeProcess()
    start_windows.mysql_process_owned = False
    start_windows.app_process = None
    start_windows.is_shutting_down = False

    with (
        mock.patch.object(start_windows, "stop_mysql_gracefully") as stop_mysql,
        mock.patch.object(start_windows, "get_current_dir", return_value=str(tmp_path)),
        mock.patch.object(start_windows, "remove_pid"),
    ):
        start_windows.cleanup({})

    stop_mysql.assert_not_called()
    assert start_windows.mysql_process is None
    assert start_windows.mysql_process_owned is False


def test_explicit_environment_is_preserved_by_run_prod():
    source = (REPO_ROOT / "scripts" / "running" / "run_prod.py").read_text(encoding="utf-8")
    assert "os.environ.setdefault('comfyui_env', 'prod')" in source
    assert "os.environ['comfyui_env'] = 'prod'" not in source


def test_stop_batch_has_no_global_mysqld_image_kill():
    source = (REPO_ROOT / "stop.bat").read_text(encoding="utf-8").lower()
    assert "taskkill /f /im mysqld.exe" not in source
    assert "safe pid-based stop is unavailable" in source


def test_start_launcher_records_its_own_supervisor_pid():
    source = (REPO_ROOT / "scripts" / "launchers" / "start_windows.py").read_text(encoding="utf-8")
    assert 'add_pid(os.getpid(), "python.exe", current_dir)' in source
