#!/usr/bin/env python3
"""
Static lint for blocking calls, missing timeout guards, and UnboundLocalError risks.

Rules:
  R1  error    async function calls blocking requests API
  R2  error    async function calls blocking time.sleep()
  R3  error    async function calls blocking urllib.request.urlopen()
  R4  error    Future.result() without explicit timeout=
  R5  warning  awaited coroutine is not guarded by asyncio.wait_for()
  R6  error    `with ThreadPoolExecutor()` (shutdown(wait=True) fake-timeout)
  R7  error    function references a name before its in-function import
               (UnboundLocalError: import binds the name for the whole function)
  R8  error    tests/: module-level `sys.modules['name'] = ...` stub assignment
               (use tests/base/test_isolation.py stub_modules instead; restores
               sys.modules entry AND parent package attribute even on ImportError)
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
    "temp",
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


_NESTED_SCOPE_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _iter_own_scope(node: ast.AST):
    """Yield AST nodes in this function body, without entering nested scopes."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _NESTED_SCOPE_TYPES):
            continue
        yield child
        yield from _iter_own_scope(child)


def _import_bound_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            names.append(alias.asname or alias.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            if alias.name == "*":
                continue
            names.append(alias.asname or alias.name)
    return names


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

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_r7(node)
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
        self._check_r7(node)
        self.generic_visit(node)

    def _check_r7(self, node: ast.AST) -> None:
        """R7: in-function import binds the name for the whole function.

        A Load of that name on an earlier line is UnboundLocalError at runtime
        (the 2026-08-21 download_queue silent stall). Nested functions are
        their own scopes and are checked separately via visit_*FunctionDef.
        """
        import_lines: dict[str, int] = {}
        load_nodes: dict[str, list[ast.AST]] = {}
        for child in _iter_own_scope(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for bound in _import_bound_names(child):
                    import_lines.setdefault(bound, child.lineno)
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                load_nodes.setdefault(child.id, []).append(child)

        for name, import_lineno in import_lines.items():
            for ref in load_nodes.get(name, []):
                if getattr(ref, "lineno", 0) < import_lineno:
                    self.add(
                        "R7",
                        "error",
                        ref,
                        f"function references '{name}' before its in-function import "
                        "(UnboundLocalError risk)",
                    )

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if not is_thread_pool_executor_call(item.context_expr):
                continue
            # AGENTS.md 红线第 10 条：禁止用 `with ThreadPoolExecutor()` 上下文管理器。
            # with 退出会触发 shutdown(wait=True)，使后续 .result(timeout=) 假超时、
            # 调用线程卡死；即便不显式调 result，submit(asyncio.run) 也应改用模块级长寿 executor。
            # 因此只要 with 上下文是 ThreadPoolExecutor 即报 R6，不再要求块内必须出现 result(timeout=)。
            self.add(
                "R6",
                "error",
                item.context_expr,
                "ThreadPoolExecutor must not be used as a `with` context manager "
                "(exit triggers shutdown(wait=True)); use a module-level long-lived executor instead",
            )
        self.generic_visit(node)


class TestSysModulesStubVisitor(ast.NodeVisitor):
    """R8: tests/ 内模块级 `sys.modules['name'] = ...` 裸 stub 赋值。

    历史上多次 CI 全量跑连锁失败的根因：模块级注入未恢复，或
    "尾部恢复"因 import 中断未执行（d01ec49e）。官方替代是
    tests/base/test_isolation.py 的 stub_modules（try/finally 恢复，
    同时还原父包属性）。函数/类/with 块内的赋值（时序可控）不拦截；
    动态键（sys.modules[spec.name]）不拦截。
    """

    _SCOPE_TYPES = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.With,
        ast.AsyncWith,
        ast.Lambda,
    )

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

    def visit_Module(self, node: ast.Module) -> None:
        self._walk_stmts(node.body)

    def _walk_stmts(self, stmts) -> None:
        for stmt in stmts:
            if isinstance(stmt, self._SCOPE_TYPES):
                continue
            if isinstance(stmt, ast.Assign):
                self._check_assign(stmt)
            for field in ("body", "orelse", "finalbody"):
                sub = getattr(stmt, field, None)
                if isinstance(sub, list):
                    self._walk_stmts(sub)

    def _check_assign(self, stmt: ast.Assign) -> None:
        for target in stmt.targets:
            if not (
                isinstance(target, ast.Subscript)
                and dotted_name(target.value) == "sys.modules"
            ):
                continue
            slice_node = target.slice
            if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
                self.add(
                    "R8",
                    "error",
                    stmt,
                    f"module-level sys.modules[{slice_node.value!r}] stub assignment; "
                    "use tests/base/test_isolation.py stub_modules() instead "
                    "(restores sys.modules entry and parent package attribute)",
                )


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        parts = set(path.relative_to(root).parts[:-1])
        if parts.intersection(EXCLUDED_DIRS):
            continue
        yield path


def iter_test_python_files(root: Path) -> Iterable[Path]:
    """tests/ 目录（主规则集排除它，R8 专用）。"""
    tests_root = root / "tests"
    if not tests_root.is_dir():
        return
    for path in tests_root.rglob("*.py"):
        parts = set(path.relative_to(root).parts[:-1])
        if parts.intersection({"__pycache__"}):
            continue
        if path.name == "test_isolation.py" and "base" in parts:
            continue  # 官方隔离工具自身
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


def scan_file(path: Path, *, include_main_rules: bool = True, r8: bool = False) -> list[Finding]:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8-sig", errors="ignore")
    tree = ast.parse(source, filename=str(path))
    findings: list[Finding] = []
    if include_main_rules:
        visitor = BlockingCallVisitor(path)
        visitor.visit(tree)
        findings.extend(visitor.findings)
    if r8:
        r8_visitor = TestSysModulesStubVisitor(path)
        r8_visitor.visit(tree)
        findings.extend(r8_visitor.findings)
    return findings


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

    # R8：tests/ 目录的模块级 sys.modules stub 赋值（主规则集不扫 tests）
    for path in iter_test_python_files(root):
        try:
            findings = scan_file(path, include_main_rules=False, r8=True)
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
