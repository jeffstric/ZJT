# -*- coding: utf-8 -*-
"""把历史缺陷补丁打进临时副本，先确认测试在正确代码上通过，再确认改坏后会失败。

不修改当前工作区。临时目录放在仓库所在盘，方便用硬链接减少复制。

用法:
    python scripts/testing/run_bug_replay.py
    python scripts/testing/run_bug_replay.py --id 2026-10-21-sse-silent-stall
    python scripts/testing/run_bug_replay.py --list
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.constant import BUG_REPLAY_PYTEST_TIMEOUT_SECONDS
from scripts.testing.regression_catalog import (
    ReplayError,
    apply_patch,
    load_entries,
    load_patch,
)

CATALOG_DIR = ROOT / "tests" / "regressions"

# 这些目录不是这三条试点要执行的代码，整目录跳过，避免把缓存和依赖复制进临时目录。
_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "bin",
    "data",
    "e2e-results",
    "files",
    "gui-test-screenshots",
    "logs",
    "node_modules",
    "sample",
    "temp",
    "tmp_browser",
    "upload",
    "uv-cache",
    "venv",
}


def _patch_file(entry: dict) -> Path | None:
    raw = entry.get("patch") or ""
    if not isinstance(raw, str) or not raw.strip():
        return None
    return (CATALOG_DIR / raw).resolve()


def _replay_tests(entry: dict) -> list[str]:
    chosen = entry.get("replay_tests") or entry.get("tests") or []
    return [item for item in chosen if item]


def _writable_paths(patch: dict) -> set[str]:
    paths = set()
    for item in patch.get("replaces") or []:
        rel = (item.get("path") or "").replace("\\", "/")
        if rel:
            paths.add(rel)
    return paths


def _copy_repo(dst: Path, writable: set[str]) -> None:
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS]
        rel_dir = Path(dirpath).relative_to(ROOT)
        target_dir = dst / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            rel = (rel_dir / filename).as_posix()
            source = Path(dirpath) / filename
            target = target_dir / filename
            if rel in writable:
                shutil.copy2(source, target)
                continue
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)


def _temp_dir() -> Path:
    base = Path(ROOT.anchor) / "tmp" / "comfyui-bug-replay"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="replay-", dir=str(base)))


def _run_pytest(cwd: Path, tests: list[str]) -> tuple[int, str, bool]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        *tests,
        "-q",
        "--tb=line",
        "-p",
        "no:cacheprovider",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(cwd)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=BUG_REPLAY_PYTEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return 124, stdout + "\n" + stderr, True
    return completed.returncode, (completed.stdout or "") + (completed.stderr or ""), False


def _tail(text: str, limit: int = 40) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-limit:])


def _classify_patched(returncode: int, timed_out: bool) -> str:
    if timed_out:
        return "caught"
    if returncode == 0:
        return "blind"
    if returncode == 5:
        return "infra"
    return "caught"


def _restore(temp_dir: Path, patch: dict) -> None:
    for rel in _writable_paths(patch):
        shutil.copy2(ROOT / rel, temp_dir / rel)
    for item in patch.get("creates") or []:
        created = temp_dir / (item.get("path") or "")
        if created.is_file():
            created.unlink()


def replay_entry(entry: dict, temp_dir: Path) -> str:
    """返回 caught / blind / infra / skipped。temp_dir 是一份干净副本。"""
    bug_id = entry.get("id") or entry["path"].stem
    tests = _replay_tests(entry)
    patch_path = _patch_file(entry)
    if patch_path is None:
        print(f"[跳过] {bug_id} 还没有改坏补丁")
        return "skipped"
    if not tests:
        print(f"[失败] {bug_id} 写了补丁，但没有要跑的测试")
        return "infra"
    if not patch_path.is_file():
        print(f"[失败] {bug_id} 找不到补丁 {patch_path}")
        return "infra"

    patch = load_patch(patch_path)
    try:
        print(f"[干净] {bug_id} 运行 {' '.join(tests)}")
        clean_code, clean_out, clean_timeout = _run_pytest(temp_dir, tests)
        if clean_timeout or clean_code != 0:
            print(f"[失败] {bug_id} 在正确代码上没有通过")
            print(_tail(clean_out))
            return "infra"
        apply_patch(temp_dir, patch)
        print(f"[改坏] {bug_id} 运行 {' '.join(tests)}")
        bad_code, bad_out, bad_timeout = _run_pytest(temp_dir, tests)
        kind = _classify_patched(bad_code, bad_timeout)
        if kind == "caught":
            print(f"[抓住] {bug_id} 改坏之后测试没有通过")
            return "caught"
        if kind == "blind":
            print(f"[没抓住] {bug_id} 改坏之后测试仍然通过")
            print(_tail(bad_out))
            return "blind"
        print(f"[失败] {bug_id} 改坏之后测试没有正常执行")
        print(_tail(bad_out))
        return "infra"
    finally:
        _restore(temp_dir, patch)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="故意改坏历史缺陷，确认对应测试会失败")
    parser.add_argument("--id", action="append", default=[], help="只回放这一条，可重复")
    parser.add_argument("--list", action="store_true", help="只列出清单")
    args = parser.parse_args(argv)

    entries = load_entries(CATALOG_DIR)
    if args.id:
        wanted = set(args.id)
        entries = [entry for entry in entries if entry.get("id") in wanted]
        missing = wanted - {entry.get("id") for entry in entries}
        for bug_id in sorted(missing):
            print(f"[失败] 清单里没有 {bug_id}")
        if missing:
            return 2

    if args.list:
        for entry in entries:
            patch = "有补丁" if _patch_file(entry) else "无补丁"
            tests = ", ".join(_replay_tests(entry)) or "(还没有永久测试)"
            print(f"{entry.get('id')}\t{patch}\t{tests}")
        return 0

    selected = [entry for entry in entries if _patch_file(entry)]
    if not selected:
        print("没有带改坏补丁的条目")
        return 0

    writable = set()
    for entry in selected:
        writable.update(_writable_paths(load_patch(_patch_file(entry))))
    temp_dir = _temp_dir()
    results = []
    try:
        print(f"[复制] {temp_dir}")
        _copy_repo(temp_dir, writable)
        for entry in selected:
            try:
                results.append(replay_entry(entry, temp_dir))
            except ReplayError as exc:
                print(f"[失败] {entry.get('id')}: {exc}")
                results.append("infra")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    caught = results.count("caught")
    blind = results.count("blind")
    infra = results.count("infra")
    print(f"完成：抓住 {caught}，没抓住 {blind}，没跑成 {infra}")
    if infra:
        return 2
    if blind:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
