#!/usr/bin/env python3
"""
Static lint for blocking calls and missing timeout guards.
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".pytest_tmp",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "alembic",
    "auto_test",
    "bin",
    "node_modules",
    "tests",
    "venv",
}


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    path: Path
    line: int
    message: str


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def is_timeout_keyword(call: ast.Call) -> bool:
    return any(keyword.arg == "timeout" for keyword in call.keywords)


def is_result_call(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Attribute) and call.func.attr == "result"


def is_thread_pool_executor_call(expr: ast.AST) -> bool:
    if isinstance(expr, ast.Call):
        name = dotted_name(expr.func)
    else:
        name = dotted_name(expr)
    return name in {
        "ThreadPoolExecutor",
        "concurrent.futures.ThreadPoolExecutor",
        "futures.ThreadPoolExecutor",
    }


def is_wait_for_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and dotted_name(node.func) in {
        "asyncio.wait_for",
        "wait_for",
    }


class BlockingCallVisitor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.findings: list[Finding] = []

    def add(self, rule: str, severity: str, node: ast.AST, message: str) -> None:
        self.findings.append(
            Finding(
                rule=rule,
                severity=severity,
                path=self.path,
                line=getattr(node, "lineno", 1),
                message=message,
            )
        )

    def visit_Call(self, node: ast.Call) -> None:
        if is_result_call(node) and not is_timeout_keyword(node):
            self.add(
                "R4",
                "error",
                node,
                "Future.result() must use an explicit timeout= keyword",
            )
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = dotted_name(child.func)
                if name in {
                    "requests.get",
                    "requests.post",
                    "requests.put",
                    "requests.delete",
                    "requests.request",
                    "requests.Session",
                }:
                    self.add("R1", "error", child, "async function calls blocking requests API")
                elif name == "time.sleep":
                    self.add("R2", "error", child, "async function calls blocking time.sleep()")
                elif name == "urllib.request.urlopen":
                    self.add("R3", "error", child, "async function calls blocking urllib.request.urlopen()")
            elif isinstance(child, ast.Await) and not is_wait_for_call(child.value):
                self.add(
                    "R5",
                    "warning",
                    child,
                    "awaited coroutine is not guarded by asyncio.wait_for(); advisory only",
                )
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        has_thread_pool = any(
            is_thread_pool_executor_call(item.context_expr) for item in node.items
        )
        if has_thread_pool:
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and is_result_call(child)
                    and is_timeout_keyword(child)
                ):
                    self.add(
                        "R6",
                        "error",
                        child,
                        "ThreadPoolExecutor context manager with result(timeout=) still waits on shutdown(wait=True)",
                    )
        self.generic_visit(node)


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        parts = set(path.relative_to(root).parts[:-1])
        if parts.intersection(EXCLUDED_DIRS):
            continue
        yield path


def load_allowlist(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    entries = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line.replace("\\", "/"))
    return entries


def is_allowed(finding: Finding, root: Path, allowlist: set[str]) -> bool:
    rel_path = finding.path.relative_to(root).as_posix()
    return (
        f"{rel_path}:{finding.line}:{finding.rule}" in allowlist
        or f"{rel_path}:{finding.rule}" in allowlist
    )


def scan_file(path: Path) -> list[Finding]:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8-sig", errors="ignore")
    tree = ast.parse(source, filename=str(path))
    visitor = BlockingCallVisitor(path)
    visitor.visit(tree)
    return visitor.findings


def emit(finding: Finding, root: Path) -> None:
    rel_path = finding.path.relative_to(root).as_posix()
    prefix = "::warning" if finding.severity == "warning" else "::error"
    print(
        f"{prefix} file={rel_path},line={finding.line}::{finding.rule} {finding.message}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--allow-file", type=Path, default=Path("scripts/lint_blocking_calls_allowlist.txt"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    allow_file = args.allow_file
    if not allow_file.is_absolute():
        allow_file = root / allow_file
    allowlist = load_allowlist(allow_file)

    error_count = 0
    for path in iter_python_files(root):
        try:
            findings = scan_file(path)
        except SyntaxError as exc:
            finding = Finding("PY", "error", path, exc.lineno or 1, f"syntax error: {exc.msg}")
            if not is_allowed(finding, root, allowlist):
                emit(finding, root)
                error_count += 1
            continue

        for finding in findings:
            if is_allowed(finding, root, allowlist):
                continue
            emit(finding, root)
            if finding.severity == "error":
                error_count += 1

    return 1 if error_count else 0


if __name__ == "__main__":
    sys.exit(main())
