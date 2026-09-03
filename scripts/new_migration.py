#!/usr/bin/env python3
"""新建 Alembic 迁移脚本脚手架。

用法:
    python scripts/new_migration.py <简短描述>

示例:
    python scripts/new_migration.py add_user_avatar
    -> alembic/versions/no_122_20260901_add_user_avatar.py

自动完成：
  1. 取当前最大 no_ 编号 +1；
  2. 取当前迁移图唯一 head 的 revision 作为 down_revision（强制单头链式衔接）；
  3. 生成符合 lint（scripts/lint_migration_names.py）规范的模板文件。
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

# 复用 lint 脚本的解析逻辑，保证脚手架与校验规则一致
sys.path.insert(0, str(Path(__file__).parent))
from lint_migration_names import NO_PATTERN, _parse_down_revisions, _parse_revision

VERSIONS_DIR = Path(__file__).parent.parent / "alembic" / "versions"
REVISION_MAX_LEN = 32

TEMPLATE = '''"""{doc}

Revision ID: {revision}
Revises: {down_revision}
Create Date: {create_date}
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= {max_len} 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '{revision}'
down_revision: Union[str, None] = '{down_revision}'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """TODO: 描述本次迁移"""
    conn = op.get_bind()
    # TODO: 在此编写迁移 SQL（务必幂等：IF NOT EXISTS / ON DUPLICATE KEY UPDATE / NOT EXISTS）
    pass


def downgrade() -> None:
    """TODO: 回滚操作；数据修复类迁移可留空（pass），避免误删数据"""
    pass
'''


def current_state() -> tuple[int, str]:
    """返回 (当前最大 no_ 编号, 当前唯一 head 的 revision)。"""
    max_no = 0
    rev_of: dict[str, Path] = {}
    down_of: dict[str, list[str]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name.startswith(".") or path.name == "__init__.py":
            continue
        m = NO_PATTERN.match(path.name)
        if m:
            max_no = max(max_no, int(m.group(1)))
        content = path.read_text(encoding="utf-8")
        rev = _parse_revision(content)
        if rev:
            rev_of[rev] = path
            down_of[rev] = _parse_down_revisions(content)
    referenced = {d for downs in down_of.values() for d in downs}
    heads = [rev for rev in rev_of if rev not in referenced]
    if len(heads) != 1:
        print(f"错误：当前迁移图存在 {len(heads)} 个 head: {heads}，请先解决多头再新建迁移")
        sys.exit(1)
    return max_no, heads[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("description", help="简短描述，小写字母/数字/下划线，如 add_user_avatar")
    args = parser.parse_args()

    desc = args.description.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]+", desc):
        print(f"错误：描述只能包含小写字母/数字/下划线: {desc}")
        return 1

    max_no, head_rev = current_state()
    next_no = max_no + 1
    today = datetime.now().strftime("%Y%m%d")

    # revision id：日期_描述，必须 <= 32 字符
    revision = f"{today}_{desc}"
    if len(revision) > REVISION_MAX_LEN:
        revision = revision[:REVISION_MAX_LEN].rstrip("_")
        print(f"提示：revision 超长已截断为 {revision}")

    filename = f"no_{next_no}_{today}_{desc}.py"
    target = VERSIONS_DIR / filename
    if target.exists():
        print(f"错误：文件已存在: {target}")
        return 1

    target.write_text(TEMPLATE.format(
        doc=desc.replace("_", " "),
        revision=revision,
        down_revision=head_rev,
        create_date=datetime.now().strftime("%Y-%m-%d"),
        max_len=REVISION_MAX_LEN,
    ), encoding="utf-8")

    print(f"已创建: {target}")
    print(f"  revision      = {revision}")
    print(f"  down_revision = {head_rev}（当前唯一 head）")
    print("请编辑 upgrade()/downgrade() 后运行 python scripts/lint_migration_names.py 校验")
    return 0


if __name__ == "__main__":
    sys.exit(main())
