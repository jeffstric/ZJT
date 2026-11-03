#!/usr/bin/env python3
"""
Lint unconditional ai_tools status writes (S1).

`AIToolsModel.update` / `update_with_cdn_sync` / `update_by_project_id` /
`update_by_project_id_with_cdn_sync` 的 WHERE 不带 status 条件。业务代码若传入
`status=`，会把用户刚写入的 CANCELLED 覆盖成 PROCESSING / COMPLETED / FAILED。
状态迁移必须走 `transition_status` 或 `transition_with_cdn_sync`，并写明 from_statuses。

只拦截关键字参数名恰好为 status 的调用。`**kwargs` 无法静态判断，不报。
`model/ai_tools.py` 内部转发、tests/、temp/、enterprise/ 不扫描。

Usage:
  python scripts/lint_ai_tool_status_cas.py
  python scripts/lint_ai_tool_status_cas.py --root .
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from dataclasses import dataclass
from pathlib import Path


STATUS_METHODS = {
    "update",
    "update_with_cdn_sync",
    "update_by_project_id",
    "update_by_project_id_with_cdn_sync",
}

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
    "enterprise",
    "node_modules",
    "temp",
    "tests",
    "venv",
}

# 模型内部用 **kwargs 转发，本身不是业务状态写入。
EXCLUDED_FILES = {
    Path("model") / "ai_tools.py",
}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    message: str


def _is_ai_tools_model(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "AIToolsModel"
    if isinstance(node, ast.Attribute):
        return node.attr == "AIToolsModel"
    return False


class StatusWriteVisitor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.findings: list[Finding] = []

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in STATUS_METHODS and _is_ai_tools_model(func.value):
            for keyword in node.keywords:
                if keyword.arg == "status":
                    self.findings.append(Finding(
                        self.path,
                        keyword.lineno,
                        f"S1 {func.attr}() 禁止传入 status=；请改用 AIToolsModel.transition_status / transition_with_cdn_sync",
                    ))
        self.generic_visit(node)


def _excluded(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return True
    relative_posix = Path(*relative.parts)
    return relative_posix in EXCLUDED_FILES or relative_posix.as_posix() in {
        item.as_posix() for item in EXCLUDED_FILES
    }


def scan_root(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in EXCLUDED_DIRS]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            if _excluded(path, root):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError:
                continue
            visitor = StatusWriteVisitor(path)
            visitor.visit(tree)
            findings.extend(visitor.findings)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint unconditional ai_tools status writes")
    parser.add_argument("--root", default=".", help="repository root to scan")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    findings = scan_root(root)
    for finding in findings:
        try:
            display = finding.path.relative_to(root)
        except ValueError:
            display = finding.path
        print(f"{display}:{finding.line}: {finding.message}")
    if findings:
        print(f"lint_ai_tool_status_cas: {len(findings)} violation(s)")
        return 1
    print("lint_ai_tool_status_cas: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
