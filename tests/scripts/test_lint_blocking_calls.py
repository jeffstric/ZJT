import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "lint_blocking_calls.py"


def _load_lint_module():
    spec = importlib.util.spec_from_file_location("lint_blocking_calls", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_lint(root: Path, allow_file: Path | None = None):
    command = [sys.executable, str(SCRIPT), "--root", str(root)]
    if allow_file:
        command.extend(["--allow-file", str(allow_file)])
    return subprocess.run(command, text=True, capture_output=True)


def write_py(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_blocks_requests_call_inside_async_function(tmp_path):
    write_py(
        tmp_path,
        "bad_async_requests.py",
        """
import requests

async def handler():
    return requests.get("https://example.com")
""",
    )

    result = run_lint(tmp_path)

    assert result.returncode == 1
    assert "R1" in result.stdout
    assert "bad_async_requests.py" in result.stdout


def test_blocks_time_sleep_inside_async_function(tmp_path):
    write_py(
        tmp_path,
        "bad_async_sleep.py",
        """
import time

async def handler():
    time.sleep(1)
""",
    )

    result = run_lint(tmp_path)

    assert result.returncode == 1
    assert "R2" in result.stdout


def test_blocks_urllib_urlopen_inside_async_function(tmp_path):
    write_py(
        tmp_path,
        "bad_async_urlopen.py",
        """
import urllib.request

async def handler():
    return urllib.request.urlopen("https://example.com")
""",
    )

    result = run_lint(tmp_path)

    assert result.returncode == 1
    assert "R3" in result.stdout


def test_future_result_requires_timeout_keyword(tmp_path):
    write_py(
        tmp_path,
        "future_result.py",
        """
def bad_empty(future):
    return future.result()

def bad_positional(future):
    return future.result(10)

def good(future):
    return future.result(timeout=10)
""",
    )

    result = run_lint(tmp_path)

    assert result.returncode == 1
    assert result.stdout.count("R4") == 2


def test_blocks_thread_pool_with_context_manager_fake_timeout(tmp_path):
    write_py(
        tmp_path,
        "fake_timeout.py",
        """
import concurrent.futures

def run(coro):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(lambda: coro)
        return future.result(timeout=1)
""",
    )

    result = run_lint(tmp_path)

    assert result.returncode == 1
    assert "R6" in result.stdout


def test_allowlist_suppresses_existing_violation(tmp_path):
    bad_file = write_py(
        tmp_path,
        "allowed.py",
        """
def bad(future):
    return future.result()
""",
    )
    allow_file = tmp_path / "allowlist.txt"
    allow_file.write_text(f"{bad_file.relative_to(tmp_path).as_posix()}:R4\n", encoding="utf-8")

    result = run_lint(tmp_path, allow_file)

    assert result.returncode == 0
    assert "R4" not in result.stdout


def test_wait_for_advisory_is_warning_only(tmp_path):
    write_py(
        tmp_path,
        "warn_only.py",
        """
async def long_task():
    return await do_work()
""",
    )

    result = run_lint(tmp_path)

    assert result.returncode == 0
    assert "::warning" in result.stdout
    assert "R5" in result.stdout


def _lint_scratch():
    root = REPO_ROOT / ".pytest_tmp" / "lint_blocking_calls"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_r7_reports_reference_before_in_function_import():
    lint = _load_lint_module()
    path = write_py(
        _lint_scratch(),
        "r7_before.py",
        """
async def process():
    await asyncio.wait_for(work(), timeout=1)
    import asyncio
""",
    )
    findings = lint.scan_file(path)
    r7 = [f for f in findings if f.rule == "R7"]
    assert len(r7) == 1
    assert "asyncio" in r7[0].message


def test_r7_allows_reference_after_in_function_import():
    lint = _load_lint_module()
    path = write_py(
        _lint_scratch(),
        "r7_after.py",
        """
async def process():
    import asyncio
    await asyncio.wait_for(work(), timeout=1)
""",
    )
    findings = lint.scan_file(path)
    assert [f for f in findings if f.rule == "R7"] == []


def test_r7_nested_function_scope_is_independent():
    lint = _load_lint_module()
    path = write_py(
        _lint_scratch(),
        "r7_nested.py",
        """
def outer():
    import asyncio
    async def inner():
        await asyncio.sleep(0)
        import asyncio
    return inner
""",
    )
    findings = lint.scan_file(path)
    r7 = [f for f in findings if f.rule == "R7"]
    assert len(r7) == 1
    assert r7[0].line == 5


def test_r7_except_clause_reference_before_import():
    lint = _load_lint_module()
    path = write_py(
        _lint_scratch(),
        "r7_except.py",
        """
async def process():
    try:
        await work()
    except asyncio.TimeoutError:
        return
    import asyncio
""",
    )
    findings = lint.scan_file(path)
    r7 = [f for f in findings if f.rule == "R7"]
    assert len(r7) == 1
    assert "asyncio" in r7[0].message
