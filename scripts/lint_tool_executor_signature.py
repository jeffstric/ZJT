#!/usr/bin/env python3
"""
Lint duck-typed tool executor signature consistency (execute_tool interface).

背景：`ExpertAgent.tool_executor` 是鸭子类型（script_writer_core/agents/expert_agent.py），
运行期实际对象可能是 ToolExecutor，也可能是 services/ 下的故事板包装器，二者无共同
基类。调用方新增关键字参数（如 model_id）而某个实现者未同步时，只有运行到该路径才抛
TypeError（参见修复提交 f2f5074b）。本脚本以"调用点关键字集合 ⊆ 每个实现者签名"
的保守规则静态拦截这类分叉。

Rules:
  T1  error    定义了 execute_tool 的类/函数不接受某个调用点透传的关键字参数，
               且没有 **kwargs 透传
  T2  warning  调用点使用 **kwargs 解包传参，无法静态枚举，需人工确认实现者签名

局限（有意为之，保持零依赖）：
  - 只比对关键字参数；纯位置参数的个数/顺序不匹配不在检查范围。
  - 无法区分"恰好同名但不可互换"的方法；InterfaceMethods 清单之外的鸭子接口
    不在检查范围（需要扩展时修改 INTERFACE_METHODS）。
  - enterprise/ 为独立仓，默认不扫描，由 enterprise 仓自行接入。

Usage:
  python scripts/lint_tool_executor_signature.py
  python scripts/lint_tool_executor_signature.py --root . --allow-file scripts/lint_tool_executor_signature_allowlist.txt
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path


# 鸭子类型接口方法清单：调用点透传的关键字参数，必须被所有同名实现者接受。
INTERFACE_METHODS = ("execute_tool",)

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
    "enterprise",  # 独立仓，自行接入
    "node_modules",
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


@dataclass(frozen=True)
class Implementer:
    """一个 execute_tool 定义点。"""

    path: Path
    line: int
    qualname: str
    accepted: frozenset  # 可接受的关键字参数名
    has_varkw: bool  # 是否有 **kwargs


class InterfaceVisitor(ast.NodeVisitor):
    """收集接口调用点透传的关键字，以及所有同名实现者的签名。"""

    def __init__(self, path: Path):
        self.path = path
        # method_name -> 调用点透传过的关键字参数名集合
        self.callsite_kwargs: dict[str, set[str]] = {name: set() for name in INTERFACE_METHODS}
        self.implementers: list[Implementer] = []
        self.findings: list[Finding] = []
        self._class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def _visit_function(self, node) -> None:
        if node.name in INTERFACE_METHODS:
            args = node.args
            accepted = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
            accepted.discard("self")
            accepted.discard("cls")
            qualname = ".".join([*self._class_stack, node.name]) if self._class_stack else node.name
            self.implementers.append(
                Implementer(
                    path=self.path,
                    line=node.lineno,
                    qualname=qualname,
                    accepted=frozenset(accepted),
                    has_varkw=args.kwarg is not None,
                )
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in INTERFACE_METHODS:
            for keyword in node.keywords:
                if keyword.arg is None:
                    self.findings.append(
                        Finding(
                            "T2",
                            "warning",
                            self.path,
                            node.lineno,
                            f"call site unpacks **kwargs into .{func.attr}() — cannot verify statically",
                        )
                    )
                else:
                    self.callsite_kwargs[func.attr].add(keyword.arg)
        self.generic_visit(node)


def iter_python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        try:
            parts = set(path.relative_to(root).parts[:-1])
        except ValueError:
            continue
        if parts.intersection(EXCLUDED_DIRS):
            continue
        # pytest basetemp / 临时检出等 .tmp* 目录（如 .tmp_pytest 下的测试夹具）不参与扫描
        if any(part.startswith(".tmp") for part in parts):
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


def scan_file(path: Path) -> InterfaceVisitor:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8-sig", errors="ignore")
    tree = ast.parse(source, filename=str(path))
    visitor = InterfaceVisitor(path)
    visitor.visit(tree)
    return visitor


def check_implementers(
    implementers: list[Implementer],
    callsite_kwargs: dict[str, set[str]],
) -> list[Finding]:
    """T1：每个无 **kwargs 的实现者必须接受所有调用点透传的关键字。"""
    findings: list[Finding] = []
    for impl in implementers:
        if impl.has_varkw:
            continue
        method = impl.qualname.rsplit(".", 1)[-1]
        missing = callsite_kwargs.get(method, set()) - impl.accepted
        if missing:
            findings.append(
                Finding(
                    "T1",
                    "error",
                    impl.path,
                    impl.line,
                    f"{impl.qualname} 不接受调用点透传的关键字参数: {', '.join(sorted(missing))}"
                    "（鸭子接口签名必须与所有 .execute_tool() 调用点保持一致，"
                    "或改用 **kwargs 透传）",
                )
            )
    return findings


def emit(finding: Finding, root: Path) -> None:
    rel_path = finding.path.relative_to(root).as_posix()
    prefix = "::warning" if finding.severity == "warning" else "::error"
    print(f"{prefix} file={rel_path},line={finding.line}::{finding.rule} {finding.message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--allow-file",
        type=Path,
        default=Path("scripts/lint_tool_executor_signature_allowlist.txt"),
    )
    return parser.parse_args()


def _force_utf8_stdout() -> None:
    """Windows 管道下 stdout 默认 GBK，与 CI/测试的 UTF-8 解码不一致；统一为 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main() -> int:
    _force_utf8_stdout()
    args = parse_args()
    root = args.root.resolve()
    allow_file = args.allow_file
    if not allow_file.is_absolute():
        allow_file = root / allow_file
    allowlist = load_allowlist(allow_file)

    callsite_kwargs: dict[str, set[str]] = {name: set() for name in INTERFACE_METHODS}
    implementers: list[Implementer] = []
    findings: list[Finding] = []

    for path in iter_python_files(root):
        try:
            visitor = scan_file(path)
        except SyntaxError as exc:
            findings.append(Finding("PY", "error", path, exc.lineno or 1, f"syntax error: {exc.msg}"))
            continue
        for method, kwargs in visitor.callsite_kwargs.items():
            callsite_kwargs[method].update(kwargs)
        implementers.extend(visitor.implementers)
        findings.extend(visitor.findings)  # T2 warning

    findings.extend(check_implementers(implementers, callsite_kwargs))

    error_count = 0
    for finding in findings:
        if is_allowed(finding, root, allowlist):
            continue
        emit(finding, root)
        if finding.severity == "error":
            error_count += 1

    return 1 if error_count else 0


if __name__ == "__main__":
    sys.exit(main())
