"""用户模块跨平台目录解析和路径越界防护。"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable

from config.constant import USER_MODULE_DEFAULT_ROOT_RELATIVE, USER_MODULE_ROOT_ENV_NAME


LAYOUT_DIRECTORIES = (
    "staging",
    "modules",
    "state",
    "envs",
    "runtime",
)


def get_project_root() -> Path:
    # 运行时位于主仓根/module_runtime/（develop_f1214 起自 enterprise 包迁入），项目根是 parents[1]
    return Path(__file__).resolve().parents[1]


def get_user_module_root(project_root: Path | None = None) -> Path:
    """环境变量优先，其次 YAML 配置，最后回退到 data/user_modules。"""

    project = Path(project_root or get_project_root()).resolve()
    configured = os.environ.get(USER_MODULE_ROOT_ENV_NAME, "").strip()
    if not configured:
        try:
            from config.config_util import get_config_value

            configured = str(get_config_value("user_modules", "root", default="") or "").strip()
        except Exception:
            configured = ""
    root = Path(configured) if configured else Path(USER_MODULE_DEFAULT_ROOT_RELATIVE)
    if not root.is_absolute():
        root = project / root
    root = root.resolve(strict=False)
    if root == project or root in project.parents:
        raise ValueError("用户模块根目录不能是项目目录或其父目录")
    return root


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def _reject_links_between(root: Path, target: Path) -> None:
    current = root
    if current.exists() and (current.is_symlink() or _is_reparse_point(current)):
        raise ValueError(f"用户模块路径不能经过链接或 reparse point: {current}")
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists() and (current.is_symlink() or _is_reparse_point(current)):
            raise ValueError(f"用户模块路径不能经过链接或 reparse point: {current}")


def resolve_within_root(root: Path, *parts: str, must_exist: bool = False) -> Path:
    base = Path(root).resolve(strict=False)
    for part in parts:
        candidate_part = Path(part)
        if candidate_part.is_absolute() or ".." in candidate_part.parts:
            raise ValueError(f"非法模块路径片段: {part}")
    unresolved_candidate = base.joinpath(*parts)
    _reject_links_between(base, unresolved_candidate)
    candidate = unresolved_candidate.resolve(strict=must_exist)
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("模块路径越界") from exc
    return candidate


def ensure_user_module_layout(root: Path | None = None) -> Path:
    module_root = Path(root or get_user_module_root()).resolve(strict=False)
    module_root.mkdir(parents=True, exist_ok=True)
    _reject_links_between(module_root, module_root)
    for directory in LAYOUT_DIRECTORIES:
        resolve_within_root(module_root, directory).mkdir(parents=True, exist_ok=True)
    return module_root


def module_release_path(root: Path, module_id: str, release_name: str) -> Path:
    return resolve_within_root(root, "modules", module_id, "releases", release_name)


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """同目录临时文件 + os.replace，兼容 Windows/Linux/macOS。"""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            json.dump(payload, temp_file, ensure_ascii=False, indent=2, sort_keys=True)
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_name = temp_file.name
        os.replace(temp_name, destination)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_write_text(path: Path, content: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_name = temp_file.name
        os.replace(temp_name, destination)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)
