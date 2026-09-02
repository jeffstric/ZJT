import importlib.util
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "lint_tool_executor_signature.py"


def _load_lint_module():
    spec = importlib.util.spec_from_file_location("lint_tool_executor_signature", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_lint(root: Path, allow_file: Path | None = None):
    command = [sys.executable, str(SCRIPT), "--root", str(root)]
    if allow_file:
        command.extend(["--allow-file", str(allow_file)])
    return subprocess.run(command, text=True, capture_output=True, encoding="utf-8")


def write_py(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


CALLER = '''
class ExpertAgent:
    def __init__(self, tool_executor, model_id=None):
        self.tool_executor = tool_executor
        self.model_id = model_id

    def run(self, tool_name, tool_args):
        return self.tool_executor.execute_tool(
            tool_name=tool_name,
            tool_args=tool_args,
            user_id="1",
            world_id="2",
            auth_token="token",
            model_id=self.model_id,
        )
'''

FULL_IMPL = '''
class ToolExecutor:
    def execute_tool(self, tool_name, tool_args, user_id, world_id, auth_token,
                     model_id=None):
        return {"ok": True}
'''

STALE_IMPL = '''
class StoryboardAgentVideoToolExecutor:
    def __init__(self, delegate):
        self._delegate = delegate

    def execute_tool(self, tool_name, tool_args, user_id, world_id, auth_token):
        return self._delegate.execute_tool(tool_name, tool_args, user_id, world_id, auth_token)
'''


def test_passes_when_all_implementers_accept_callsite_kwargs(tmp_path):
    write_py(tmp_path, "caller.py", CALLER)
    write_py(tmp_path, "impl.py", FULL_IMPL)

    result = run_lint(tmp_path)

    assert result.returncode == 0
    assert "T1" not in result.stdout


def test_flags_implementer_missing_callsite_kwarg(tmp_path):
    """回归 f2f5074b：调用方新增 model_id 而包装器未同步时必须拦截。"""
    write_py(tmp_path, "caller.py", CALLER)
    write_py(tmp_path, "impl.py", FULL_IMPL)
    write_py(tmp_path, "wrapper.py", STALE_IMPL)

    result = run_lint(tmp_path)

    assert result.returncode == 1
    assert "T1" in result.stdout
    assert "StoryboardAgentVideoToolExecutor" in result.stdout
    assert "model_id" in result.stdout
    # 已同步的 ToolExecutor 不应被误报
    assert "impl.py" not in result.stdout


def test_varkw_implementer_is_exempt(tmp_path):
    write_py(tmp_path, "caller.py", CALLER)
    write_py(
        tmp_path,
        "fake.py",
        '''
class FakeDelegate:
    def execute_tool(self, tool_name, tool_args, **kwargs):
        return {"ok": True}
''',
    )

    result = run_lint(tmp_path)

    assert result.returncode == 0


def test_kwargs_unpacking_callsite_is_warning_not_error(tmp_path):
    write_py(tmp_path, "impl.py", FULL_IMPL)
    write_py(
        tmp_path,
        "dynamic_caller.py",
        '''
def run(executor, kwargs):
    return executor.execute_tool(**kwargs)
''',
    )

    result = run_lint(tmp_path)

    assert result.returncode == 0
    assert "T2" in result.stdout


def test_allowlist_suppresses_finding(tmp_path):
    write_py(tmp_path, "caller.py", CALLER)
    write_py(tmp_path, "wrapper.py", STALE_IMPL)
    allow_file = tmp_path / "allow.txt"
    allow_file.write_text("wrapper.py:T1\n", encoding="utf-8")

    result = run_lint(tmp_path, allow_file=allow_file)

    assert result.returncode == 0
    assert "T1" not in result.stdout


def test_async_implementer_is_checked(tmp_path):
    write_py(tmp_path, "caller.py", CALLER)
    write_py(
        tmp_path,
        "async_impl.py",
        '''
class AsyncExecutor:
    async def execute_tool(self, tool_name, tool_args, user_id, world_id, auth_token):
        return {"ok": True}
''',
    )

    result = run_lint(tmp_path)

    assert result.returncode == 1
    assert "AsyncExecutor" in result.stdout


def test_module_level_function_implementer_is_checked(tmp_path):
    write_py(tmp_path, "caller.py", CALLER)
    write_py(
        tmp_path,
        "func_impl.py",
        '''
def execute_tool(tool_name, tool_args, user_id, world_id, auth_token):
    return {"ok": True}
''',
    )

    result = run_lint(tmp_path)

    assert result.returncode == 1
    assert "func_impl.py" in result.stdout
