"""用户模块 staging 的确定性静态校验。"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List

from config.constant import (
    USER_MODULE_GENERATION_MAX_FILE_BYTES,
    USER_MODULE_GENERATION_MAX_TOTAL_BYTES,
)
from module_runtime.manifest import ModuleManifest, load_manifest
from module_runtime.secret_resolver import user_module_grantable_aliases


ALLOWED_TOP_LEVEL_IMPORTS = {
    # __future__: 类型注解语法兼容（from __future__ import annotations），无逃逸面；
    # pytest 与 src: 仅模块自带的 tests/test_driver.py 使用——测试导入被测驱动
    # （entrypoint 约定为 src.driver），pytest 只出现在交付测试文件，不进 Runner。
    "__future__",
    "pytest",
    "src",
    "unittest",
    "asyncio",
    "base64",
    "collections",
    "contextlib",
    "dataclasses",
    "datetime",
    "decimal",
    "enum",
    "functools",
    "hashlib",
    "hmac",
    "httpx",
    "json",
    "logging",
    "math",
    "pydantic",
    "random",
    "re",
    "secrets",
    "statistics",
    "string",
    "typing",
    "uuid",
}
# module_runtime 不在顶层白名单里：driver 只能 import 它的 protocol / comfyui 子模块
# （契约必需的 Completed/HealthResult/MediaRef，以及本地 ComfyUI HTTP 助手）。
# 其余子模块（runner/supervisor/generation/...）顶层都挂着 os/subprocess，
# 会成中转逃逸入口（见 review.md S2 绕过A）。
ALLOWED_MODULE_RUNTIME_SUBMODULES = {"module_runtime.protocol", "module_runtime.comfyui"}
BLOCKED_IMPORTS = {
    "api",
    "config",
    "enterprise",
    "model",
    "server",
    "services",
    "subprocess",
    "task",
    "tools",
}
# 内省逃逸属性：纯属性访问即可顺出 os/subprocess/open 等（见 review.md S2 绕过B）。
# 不含 __init__/__post_init__/__fields__ 等合法魔术方法，不误伤 dataclass/pydantic。
DUNDER_ESCAPE_ATTRIBUTES = {
    "__class__",
    "__bases__",
    "__base__",
    "__subclasses__",
    "__mro__",
    "__globals__",
    "__builtins__",
    "__import__",
    "__code__",
    "__func__",
}
BLOCKING_CALLS = {
    "requests.get",
    "requests.post",
    "requests.put",
    "requests.delete",
    "requests.request",
    "urllib.request.urlopen",
    "time.sleep",
}
BLOCKING_CALL_PREFIXES = (
    "httpx.Client",
    "httpx.request",
    "httpx.get",
    "httpx.post",
    "httpx.put",
    "httpx.patch",
    "httpx.delete",
)
# httpx 请求方法（client.post/get/...）只接受固定关键字参数；幂等键、回调地址等
# 业务字段必须放进 json 请求体或 headers。误写成调用 kwarg 会运行时 TypeError，
# 管理员只能看到笼统的 MODULE_CALL_FAILED（runninghub.image2video_v6 首版案例）。
# get/head/options 不进集合：与 dict.get(key, default=...) 冲突且误传场景罕见。
HTTP_CALL_METHODS = {"post", "put", "patch", "delete", "request", "stream"}
# httpx.AsyncClient 是异步上下文管理器：同步 with 直接 AttributeError: __enter__
# （runinghub.ltx2.5v2 首版真实事故），必须 async with。AST 的 With/AsyncWith
# 节点天然区分两种写法，同步 With 绑定 AsyncClient 构造即拦截。
HTTP_CALL_ALLOWED_KEYWORDS = {
    "url",
    "params",
    "content",
    "data",
    "files",
    "json",
    "headers",
    "cookies",
    "auth",
    "follow_redirects",
    "timeout",
    "extensions",
    "stream",
}
DANGEROUS_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "open",
}
REQUIRED_DRIVER_METHODS = {
    "initialize",
    "health",
    "submit",
    "poll",
    "cancel",
    "handle_callback",
}
# 内网/回环 URL 字面量：外部供应商模块把这类地址拼进请求（或图床之外的硬编码），
# 供应商公网拉不到（真实事故：runninghub.qweniamgeeidtv2 局域网图片地址透传）。
# src/settings.py 豁免：本地 ComfyUI 模块的 COMFYUI_BASE_URL 是管理员配置的设备地址。
# tests/ 豁免：合同要求模块自测覆盖「图片参数为局域网地址」用例，测试体内必然出现
# 内网地址字面量；tests 不进 Runner，无透传风险。
PRIVATE_URL_PATTERN = re.compile(
    r"https?://("
    r"localhost"
    r"|127(?:\.\d{1,3}){3}"
    r"|192\.168(?:\.\d{1,3}){2}"
    r"|10(?:\.\d{1,3}){3}"
    r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
    r"|[0-9a-fA-F:]*::1"
    r")(?::\d+)?(?:/|\b)",
)


def _private_url_exempt(relative: str) -> bool:
    return relative == "src/settings.py" or relative.startswith("tests/")


def _call_name(node: ast.AST) -> str:
    parts: List[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _import_aliases(tree: ast.AST) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                local_name = item.asname or item.name.split(".", 1)[0]
                aliases[local_name] = item.name if item.asname else local_name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for item in node.names:
                if item.name == "*":
                    continue
                aliases[item.asname or item.name] = f"{node.module}.{item.name}"
    return aliases


def _resolve_call_name(node: ast.AST, aliases: Dict[str, str]) -> str:
    name = _call_name(node)
    first, separator, remainder = name.partition(".")
    target = aliases.get(first)
    if not target:
        return name
    return f"{target}.{remainder}" if separator else target


def _finding(level: str, code: str, message: str, path: str = "", line: int = 0) -> Dict:
    return {"level": level, "code": code, "message": message, "path": path, "line": line}


def _iter_function_body_nodes(fn: ast.AST):
    """遍历函数体，不进入嵌套 def/class（它们有独立作用域）。"""
    skip = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    stack = list(reversed(getattr(fn, "body", []) or []))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, skip):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _node_pos(node: ast.AST) -> tuple:
    return (getattr(node, "lineno", 0) or 0, getattr(node, "col_offset", 0) or 0)


def _keep_earliest(store: Dict[str, tuple], name: str, pos: tuple) -> None:
    prev = store.get(name)
    if prev is None or pos < prev:
        store[name] = pos


def _find_inner_import_name_shadows(fn: ast.AST) -> List[tuple]:
    """函数内 import 会把名字变成整个函数的局部变量。

    若该名字在最早一次 inner import 之前就被 Load，运行时 UnboundLocalError。
    返回 (import_line, name, use_line)；位置取最早出现，不依赖 walk 顺序。
    """
    import_pos: Dict[str, tuple] = {}
    use_pos: Dict[str, tuple] = {}
    for node in _iter_function_body_nodes(fn):
        if isinstance(node, ast.Import):
            pos = _node_pos(node)
            for item in node.names:
                local_name = item.asname or item.name.split(".", 1)[0]
                _keep_earliest(import_pos, local_name, pos)
        elif isinstance(node, ast.ImportFrom):
            pos = _node_pos(node)
            for item in node.names:
                if item.name == "*":
                    continue
                local_name = item.asname or item.name
                _keep_earliest(import_pos, local_name, pos)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            _keep_earliest(use_pos, node.id, _node_pos(node))

    shadows: List[tuple] = []
    for name, imported_at in import_pos.items():
        used_at = use_pos.get(name)
        if used_at is not None and used_at < imported_at:
            shadows.append((imported_at[0], name, used_at[0]))
    return shadows


def validate_staging(staging_dir: Path) -> Dict:
    root = Path(staging_dir).resolve(strict=True)
    findings: List[Dict] = []
    files = [path for path in root.rglob("*") if path.is_file()]
    total_size = sum(path.stat().st_size for path in files)
    if total_size > USER_MODULE_GENERATION_MAX_TOTAL_BYTES:
        findings.append(_finding("error", "TOTAL_SIZE", "草稿总大小超过限制"))

    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.stat().st_size > USER_MODULE_GENERATION_MAX_FILE_BYTES:
            findings.append(_finding("error", "FILE_SIZE", "单文件超过大小限制", relative))
        if path.is_symlink():
            findings.append(_finding("error", "SYMLINK", "staging 不允许软链接", relative))
        try:
            path.resolve(strict=True).relative_to(root)
        except ValueError:
            findings.append(_finding("error", "PATH_ESCAPE", "草稿文件解析后越界", relative))

    manifest_path = root / "manifest.json"
    manifest = None
    if not manifest_path.is_file():
        findings.append(_finding("error", "MANIFEST_MISSING", "缺少 manifest.json"))
    else:
        try:
            manifest = load_manifest(manifest_path, require_digest=False)
        except Exception as exc:
            findings.append(_finding("error", "MANIFEST_INVALID", str(exc), "manifest.json"))

    python_files = [path for path in files if path.suffix == ".py"]
    class_methods: Dict[tuple[str, str], set] = {}
    for path in python_files:
        relative = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative)
        except (UnicodeDecodeError, SyntaxError) as exc:
            findings.append(
                _finding("error", "PYTHON_SYNTAX", str(exc), relative, getattr(exc, "lineno", 0) or 0)
            )
            continue
        aliases = _import_aliases(tree)
        if not _private_url_exempt(relative):
            for match in PRIVATE_URL_PATTERN.finditer(source):
                findings.append(
                    _finding(
                        "error",
                        "URL_PRIVATE_LITERAL",
                        (
                            "代码中出现内网/回环 URL 字面量；外部供应商从公网访问不到"
                            "（本地 ComfyUI 地址只能写在 src/settings.py）"
                        ),
                        relative,
                        source[: match.start()].count("\n") + 1,
                    )
                )
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # 相对导入只能解析当前不可变 Release 内的代码，不会进入核心包；允许模块拆分文件。
                if isinstance(node, ast.ImportFrom) and node.level > 0:
                    continue
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for name in names:
                    top_level = name.split(".", 1)[0]
                    if top_level == "module_runtime":
                        # module_runtime 仅允许 protocol / comfyui 子模块，其余子模块
                        # 顶层挂 os/subprocess，是中转逃逸入口。
                        if name not in ALLOWED_MODULE_RUNTIME_SUBMODULES:
                            findings.append(
                                _finding(
                                    "error",
                                    "IMPORT_BLOCKED",
                                    f"仅允许导入 module_runtime.protocol 或 module_runtime.comfyui，不允许 {name}",
                                    relative,
                                    node.lineno,
                                )
                            )
                    elif top_level in BLOCKED_IMPORTS or top_level not in ALLOWED_TOP_LEVEL_IMPORTS:
                        findings.append(
                            _finding(
                                "error",
                                "IMPORT_BLOCKED",
                                f"不允许导入 {name}",
                                relative,
                                node.lineno,
                            )
                        )
            elif isinstance(node, ast.Call):
                name = _resolve_call_name(node.func, aliases)
                if name in BLOCKING_CALLS or any(
                    name == prefix or name.startswith(f"{prefix}.")
                    for prefix in BLOCKING_CALL_PREFIXES
                ):
                    findings.append(
                        _finding(
                            "error",
                            "BLOCKING_CALL",
                            f"不允许阻塞调用 {name}",
                            relative,
                            node.lineno,
                        )
                    )
                elif name in DANGEROUS_CALLS:
                    findings.append(
                        _finding(
                            "error",
                            "DANGEROUS_CALL",
                            f"不允许文件或动态代码调用 {name}",
                            relative,
                            node.lineno,
                        )
                    )
                elif (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in HTTP_CALL_METHODS
                    and any(
                        kw.arg and kw.arg not in HTTP_CALL_ALLOWED_KEYWORDS
                        for kw in node.keywords
                    )
                ):
                    invalid = sorted(
                        {
                            kw.arg
                            for kw in node.keywords
                            if kw.arg and kw.arg not in HTTP_CALL_ALLOWED_KEYWORDS
                        }
                    )
                    findings.append(
                        _finding(
                            "error",
                            "HTTP_CALL_INVALID_KWARG",
                            (
                                f"HTTP 调用不支持关键字参数 {', '.join(invalid)}；"
                                "业务字段（幂等键、回调地址等）必须放进 json 请求体或 headers"
                            ),
                            relative,
                            node.lineno,
                        )
                    )
            elif isinstance(node, ast.With):
                # 同步 with httpx.AsyncClient(...)：异步客户端没有同步 __enter__
                for item in node.items:
                    ctx = item.context_expr
                    if (
                        isinstance(ctx, ast.Call)
                        and isinstance(ctx.func, ast.Attribute)
                        and ctx.func.attr == "AsyncClient"
                    ):
                        findings.append(
                            _finding(
                                "error",
                                "SYNC_WITH_ASYNC_CLIENT",
                                (
                                    "httpx.AsyncClient 必须用 async with；"
                                    "同步 with 会 AttributeError: __enter__"
                                ),
                                relative,
                                node.lineno,
                            )
                        )
            elif isinstance(node, ast.ClassDef):
                methods = {
                    child.name
                    for child in node.body
                    if isinstance(child, ast.AsyncFunctionDef)
                }
                class_methods[(relative, node.name)] = methods
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for import_line, name, use_line in _find_inner_import_name_shadows(node):
                    findings.append(
                        _finding(
                            "error",
                            "INNER_IMPORT_SHADOW",
                            (
                                f"函数内 import {name} 会把该名字变成局部变量；"
                                f"第 {use_line} 行在 import 之前使用，运行时 UnboundLocalError"
                            ),
                            relative,
                            import_line,
                        )
                    )
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "submit":
                    # submit 的返回必须是 Completed/Accepted/Rejected 之一；直接
                    # return DriverError(...) 会让 Runner 端 pydantic 校验崩溃，
                    # 管理员只能看到笼统的 MODULE_CALL_FAILED。
                    for inner in _iter_function_body_nodes(node):
                        if not (
                            isinstance(inner, ast.Return)
                            and isinstance(inner.value, ast.Call)
                            and _resolve_call_name(inner.value.func, aliases).split(".")[-1] == "DriverError"
                        ):
                            continue
                        findings.append(
                            _finding(
                                "error",
                                "SUBMIT_RETURN_DRIVER_ERROR",
                                (
                                    "submit 禁止直接 return DriverError(...)；失败必须 "
                                    "return Rejected(error=DriverError(...))，异步受理 "
                                    "return Accepted(...)，同步完成 return Completed(...)"
                                ),
                                relative,
                                inner.lineno,
                            )
                        )
            elif isinstance(node, ast.Attribute) and node.attr in DUNDER_ESCAPE_ATTRIBUTES:
                # 内省逃逸：纯属性访问顺出 os/subprocess/open 等，AST 黑名单拦不住
                # （见 review.md S2 绕过B）。合法魔术方法（__init__ 等）不在集合内。
                findings.append(
                    _finding(
                        "error",
                        "DUNDER_ESCAPE",
                        f"禁止使用内省逃逸属性 {node.attr}",
                        relative,
                        node.lineno,
                    )
                )

    if manifest:
        grantable = user_module_grantable_aliases()
        invalid_secrets = [
            name for name in manifest.permissions.secret_names if name not in grantable
        ]
        if invalid_secrets:
            findings.append(
                _finding(
                    "error",
                    "SECRET_NAME_NOT_GRANTABLE",
                    (
                        "密钥名不在平台可授权清单内: "
                        + ", ".join(invalid_secrets)
                        + "；合法密钥名: "
                        + ", ".join(sorted(grantable))
                    ),
                    "manifest.json",
                )
            )
        module_name, class_name = manifest.entrypoint.split(":", 1)
        entrypoint = root.joinpath(*module_name.split(".")).with_suffix(".py")
        if not entrypoint.is_file():
            findings.append(
                _finding(
                    "error",
                    "ENTRYPOINT_MISSING",
                    f"入口文件不存在: {entrypoint.relative_to(root).as_posix()}",
                )
            )
        entrypoint_relative = entrypoint.relative_to(root).as_posix()
        methods = class_methods.get((entrypoint_relative, class_name), set())
        missing = sorted(REQUIRED_DRIVER_METHODS - methods)
        if missing:
            findings.append(
                _finding(
                    "error",
                    "DRIVER_METHODS",
                    f"Driver 缺少异步方法: {', '.join(missing)}",
                )
            )

    return {
        "ok": not any(item["level"] == "error" for item in findings),
        "findings": findings,
        "file_count": len(files),
        "total_size": total_size,
        "manifest": manifest.model_dump(mode="json") if manifest else None,
    }
