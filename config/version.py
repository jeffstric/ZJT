"""
系统版本号管理
版本号定义在 pyproject.toml 中，此处提供读取方法
"""
import re
from pathlib import Path
from typing import Optional

_cached_version: Optional[str] = None


def _read_version_from_project(project_root: Path) -> Optional[str]:
    """严格读取 ``[project].version``，避免误认工具配置中的同名字段。"""

    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.exists():
        return None
    try:
        section = ""
        for raw_line in pyproject_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            section_match = re.fullmatch(r"\[([^]]+)]", line)
            if section_match:
                section = section_match.group(1).strip()
                continue
            if section != "project" or not line.startswith("version") or "=" not in line:
                continue
            value = line.split("=", 1)[1].split("#", 1)[0].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1].strip()
                if value:
                    return value
    except (OSError, UnicodeDecodeError):
        return None
    return None


def get_app_version(project_root: Optional[Path] = None) -> str:
    """
    获取应用版本号
    优先从 pyproject.toml 读取，缓存结果以提高性能
    """
    global _cached_version
    if project_root is None and _cached_version is not None:
        return _cached_version

    root = Path(project_root).resolve() if project_root is not None else Path(__file__).parent.parent
    version = _read_version_from_project(root)
    if version:
        if project_root is None:
            _cached_version = version
        return version

    raise RuntimeError(f"无法从 {root / 'pyproject.toml'} 读取 [project].version")
