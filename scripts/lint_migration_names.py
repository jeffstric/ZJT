#!/usr/bin/env python3
"""
Static lint for Alembic migration scripts (alembic/versions/).

Rules:
  M1  error    新增迁移脚本必须使用 no_<N>_<YYYYMMDD>_<描述>.py 命名
               （存量 dated 文件见 scripts/lint_migration_names_allowlist.txt 豁免清单）
  M2  error    no_<N>_ 编号不得重复
  M3  error    迁移图必须有且仅有一个 head（down_revision 引用必须存在）
  M4  error    revision id 长度必须 <= 32 字符
               (alembic_version.version_num 为 varchar(32))

纯静态文件解析（正则提取 revision/down_revision），不依赖 git、不依赖 alembic 包。
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

VERSIONS_DIR_DEFAULT = Path("alembic/versions")
ALLOWLIST_DEFAULT = Path("scripts/lint_migration_names_allowlist.txt")

# 新迁移脚本命名：no_<编号>_<YYYYMMDD>_<描述>.py
NO_PATTERN = re.compile(r"^no_(\d+)_\d{8}_[a-z0-9_]+\.py$")

REVISION_MAX_LEN = 32

_ASSIGN = {
    "revision": re.compile(r"^revision(?::[^=\n]+)?\s*=\s*(.*?)(?=^\S|\Z)", re.M | re.S),
    "down_revision": re.compile(r"^down_revision(?::[^=\n]+)?\s*=\s*(.*?)(?=^\S|\Z)", re.M | re.S),
}


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    path: Path
    line: int
    message: str


def _extract_string_literals(text: str) -> list[str]:
    return re.findall(r"['\"]([^'\"]+)['\"]", text)


def _parse_revision(content: str) -> str | None:
    m = _ASSIGN["revision"].search(content)
    if not m:
        return None
    values = _extract_string_literals(m.group(1))
    return values[0] if values else None


def _parse_down_revisions(content: str) -> list[str]:
    m = _ASSIGN["down_revision"].search(content)
    if not m:
        return []
    return _extract_string_literals(m.group(1))


def _load_allowlist(path: Path) -> tuple[set[str], set[str]]:
    """返回 (M1 命名豁免文件名, M2 编号重复豁免文件名)。

    格式：每行一个条目，`#` 开头为注释；
    普通行为文件名（M1 豁免），`M2:文件名` 为 M2 豁免（存量编号冲突）。
    """
    m1_exempt: set[str] = set()
    m2_exempt: set[str] = set()
    if not path.exists():
        return m1_exempt, m2_exempt
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("M2:"):
            m2_exempt.add(line[3:].strip())
        else:
            m1_exempt.add(line)
    return m1_exempt, m2_exempt


def lint(versions_dir: Path, allowlist_path: Path) -> list[Finding]:
    findings: list[Finding] = []
    m1_allowlist, m2_allowlist = _load_allowlist(allowlist_path)

    files = sorted(
        p for p in versions_dir.glob("*.py")
        if not p.name.startswith(".") and p.name != "__init__.py"
    )

    # M1: 命名红线（不在豁免清单内的文件必须匹配 no_xxx 格式）
    for path in files:
        if path.name in m1_allowlist:
            continue
        if not NO_PATTERN.match(path.name):
            findings.append(Finding(
                "M1", "error", path, 1,
                "迁移脚本命名不合规：新增文件必须为 no_<N>_<YYYYMMDD>_<描述>.py "
                "(请使用 scripts/new_migration.py 生成；存量 dated 文件以豁免清单为准)",
            ))

    # M2: no_ 编号唯一
    numbers: dict[int, list[Path]] = {}
    for path in files:
        m = NO_PATTERN.match(path.name)
        if m:
            numbers.setdefault(int(m.group(1)), []).append(path)
    for number, paths in sorted(numbers.items()):
        if len(paths) > 1:
            for path in paths:
                if path.name in m2_allowlist:
                    continue
                findings.append(Finding(
                    "M2", "error", path, 1,
                    f"no_{number} 编号重复（{len(paths)} 个文件共用）",
                ))

    # 构建迁移图：revision -> down_revisions
    rev_of: dict[str, Path] = {}      # revision id -> 文件
    down_of: dict[str, list[str]] = {}  # revision id -> down revisions
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="replace")
        rev = _parse_revision(content)
        if not rev:
            findings.append(Finding(
                "M3", "error", path, 1, "未解析到 revision id，无法构建迁移图",
            ))
            continue
        if rev in rev_of:
            findings.append(Finding(
                "M3", "error", path, 1,
                f"revision id 重复: {rev}（与 {rev_of[rev].name} 冲突）",
            ))
        rev_of[rev] = path
        down_of[rev] = _parse_down_revisions(content)

        # M4: revision id 长度
        if len(rev) > REVISION_MAX_LEN:
            findings.append(Finding(
                "M4", "error", path, 1,
                f"revision id 长度 {len(rev)} > {REVISION_MAX_LEN}: {rev}",
            ))

    # M3: down_revision 引用必须存在
    for rev, downs in down_of.items():
        for down in downs:
            if down not in rev_of:
                findings.append(Finding(
                    "M3", "error", rev_of[rev], 1,
                    f"down_revision 引用了不存在的 revision: {down}（{rev} 的上游）",
                ))

    # M3: 单头强制
    referenced = {d for downs in down_of.values() for d in downs}
    heads = [rev for rev in rev_of if rev not in referenced]
    if len(heads) != 1:
        detail = ", ".join(f"{rev}({rev_of[rev].name})" for rev in sorted(heads)) or "无"
        target = rev_of[heads[0]] if heads else files[0]
        findings.append(Finding(
            "M3", "error", target, 1,
            f"迁移图存在 {len(heads)} 个 head（必须为 1 个）: {detail}。"
            "请 rebase 后改挂到当前唯一 head，或补合并迁移",
        ))

    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions-dir", type=Path, default=VERSIONS_DIR_DEFAULT)
    parser.add_argument("--allow-file", type=Path, default=ALLOWLIST_DEFAULT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    findings = lint(args.versions_dir, args.allow_file)
    errors = [f for f in findings if f.severity == "error"]
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.rule} {finding.severity}: {finding.message}")
    if errors:
        print(f"\n{len(errors)} error(s) found.")
        return 1
    print("OK: alembic migrations pass lint (single head, no_ naming, unique numbers).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
