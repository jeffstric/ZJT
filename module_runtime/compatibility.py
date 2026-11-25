"""当前核心 ABI 与用户模块 Manifest 的纯数据兼容性校验。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from config.constant import USER_MODULE_ABI_FILE_RELATIVE
from config.version import get_app_version
from module_runtime.manifest import ModuleManifest


def _numeric_version(value: str) -> tuple[int, ...]:
    match = re.match(r"^[vV]?(\d+(?:\.\d+)*)", str(value).strip())
    if not match:
        raise ValueError(f"无效版本号: {value}")
    return tuple(int(part) for part in match.group(1).split("."))


def _compare_versions(left: str, right: str) -> int:
    left_parts = _numeric_version(left)
    right_parts = _numeric_version(right)
    length = max(len(left_parts), len(right_parts))
    padded_left = left_parts + (0,) * (length - len(left_parts))
    padded_right = right_parts + (0,) * (length - len(right_parts))
    return (padded_left > padded_right) - (padded_left < padded_right)


def version_satisfies(version: str, constraint: str) -> bool:
    for expression in str(constraint or "").split(","):
        expression = expression.strip()
        if not expression:
            continue
        operator = next(
            (item for item in (">=", "<=", "==", ">", "<") if expression.startswith(item)),
            None,
        )
        if operator is None:
            return False
        comparison = _compare_versions(version, expression[len(operator) :].strip())
        if not {
            ">=": comparison >= 0,
            "<=": comparison <= 0,
            "==": comparison == 0,
            ">": comparison > 0,
            "<": comparison < 0,
        }[operator]:
            return False
    return True


def load_core_abi(project_root: Path | None = None) -> Dict[str, Any]:
    project = Path(project_root or Path(__file__).resolve().parents[1])
    abi_path = project / USER_MODULE_ABI_FILE_RELATIVE
    payload = json.loads(abi_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("abi_schema_version") != 1:
        raise ValueError("当前核心的用户模块 ABI 文件无效")
    # 智剧通版本只有一个来源：pyproject.toml。ABI JSON 只描述稳定协议集合，
    # 即使其中保留了构建时快照，也不能覆盖当前实际运行版本。
    payload["core_version"] = get_app_version(project)
    return payload


def compatibility_errors(manifest: ModuleManifest, abi: Dict[str, Any]) -> List[str]:
    checks = (
        (manifest.manifest_schema_version, "manifest_schema_versions", "manifest schema"),
        (manifest.rpc_protocol, "rpc_protocol_versions", "RPC protocol"),
        (manifest.driver_protocol, "driver_protocol_versions", "driver protocol"),
        (manifest.sdk_version, "sdk_versions", "SDK"),
        (manifest.execution_model.value, "execution_models", "execution model"),
    )
    errors = [
        f"{label} {value!r} 不受当前核心支持"
        for value, abi_key, label in checks
        if value not in abi.get(abi_key, [])
    ]
    if not version_satisfies(str(abi.get("core_version", "0")), manifest.core_compat):
        errors.append("core_compat 不包含当前核心版本")
    python_version = ".".join(map(str, sys.version_info[:3]))
    if not version_satisfies(python_version, manifest.python_compat):
        errors.append("python_compat 不包含当前 Python 版本")
    supported_media = set(abi.get("media_kinds", []))
    unsupported_media = sorted(
        {capability.media_kind.value for capability in manifest.capabilities} - supported_media
    )
    if unsupported_media:
        errors.append(f"媒体类型不受当前核心支持: {', '.join(unsupported_media)}")
    return errors


def assert_manifest_compatible(manifest: ModuleManifest, abi: Dict[str, Any] | None = None) -> None:
    errors = compatibility_errors(manifest, abi or load_core_abi())
    if errors:
        raise ValueError("用户模块与当前核心 ABI 不兼容: " + "; ".join(errors))
