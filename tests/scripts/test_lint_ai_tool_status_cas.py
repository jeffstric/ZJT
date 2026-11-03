import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "lint_ai_tool_status_cas.py"


def run_lint(root: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        text=True,
        capture_output=True,
        encoding="utf-8",
    )


def write_py(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_flags_status_keyword(tmp_path):
    write_py(tmp_path, "task/example.py", """
AIToolsModel.update(1, status=2, message="x")
AIToolsModel.update_with_cdn_sync(1, result_url="u", status=2)
""")
    result = run_lint(tmp_path)
    assert result.returncode == 1
    assert result.stdout.count("S1") == 2


def test_ignores_kwargs_and_non_status_fields(tmp_path):
    write_py(tmp_path, "task/example.py", """
AIToolsModel.update(1, result_url="u")
AIToolsModel.update(1, **updates)
""")
    result = run_lint(tmp_path)
    assert result.returncode == 0, result.stdout


def test_ignores_tests_and_model_internals(tmp_path):
    write_py(tmp_path, "tests/test_example.py", "AIToolsModel.update(1, status=2)\n")
    write_py(tmp_path, "model/ai_tools.py", "AIToolsModel.update(1, status=2)\n")
    write_py(tmp_path, "temp/example.py", "AIToolsModel.update(1, status=2)\n")
    result = run_lint(tmp_path)
    assert result.returncode == 0, result.stdout


def test_repo_has_no_status_keyword_writes():
    result = run_lint(REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
