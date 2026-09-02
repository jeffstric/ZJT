"""location 表增加 plot_role（剧情作用），并从 description 回填

Revision ID: 20260828_loc_plot_role
Revises: 71147a2ee742
Create Date: 2026-08-28
"""
from typing import Sequence, Union
import logging
import re

from alembic import op
from sqlalchemy import text

logger = logging.getLogger(__name__)

revision: str = '20260828_loc_plot_role'
down_revision: Union[str, None] = '71147a2ee742'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 与 utils/location_plot_role.py 保持一致（迁移脚本自包含，不依赖应用代码）
_PLOT_ROLE_SECTION_RE = re.compile(
    r'(?:^|\n)[ \t]*(?:剧情作用|Plot\s*Role|Narrative\s*Role)[：:][ \t]*(.*?)'
    r'(?=(?:\n[ \t]*[^\s\n：:]{1,20}[：:])|\Z)',
    re.S | re.I,
)


def _split_plot_role(description):
    desc = (description or '').strip() or None
    if not desc:
        return None, None
    match = _PLOT_ROLE_SECTION_RE.search(desc)
    if not match:
        return desc, None
    extracted = (match.group(1) or '').strip() or None
    new_desc = (desc[:match.start()] + desc[match.end():]).strip()
    new_desc = re.sub(r'\n{3,}', '\n\n', new_desc).strip() or None
    return new_desc, extracted


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'location'
          AND COLUMN_NAME = 'plot_role'
    """)).scalar()
    if not exists:
        conn.execute(text("""
            ALTER TABLE `location`
            ADD COLUMN `plot_role` TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            DEFAULT NULL COMMENT '剧情作用'
            AFTER `description`
        """))
        logger.info("[Migration] location.plot_role 列已添加")
    else:
        logger.info("[Migration] location.plot_role 已存在，跳过 ADD COLUMN")

    rows = conn.execute(text("""
        SELECT `id`, `description` FROM `location`
        WHERE `description` IS NOT NULL AND `description` <> ''
          AND (`plot_role` IS NULL OR `plot_role` = '')
    """)).fetchall()
    updated = 0
    for row in rows:
        loc_id, description = row[0], row[1]
        new_desc, plot_role = _split_plot_role(description)
        if not plot_role:
            continue
        conn.execute(
            text("UPDATE `location` SET `description` = :d, `plot_role` = :p WHERE `id` = :i"),
            {"d": new_desc, "p": plot_role, "i": loc_id},
        )
        updated += 1
    logger.info("[Migration] 从 description 回填 plot_role：%s 条", updated)


def downgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'location'
          AND COLUMN_NAME = 'plot_role'
    """)).scalar()
    if exists:
        conn.execute(text("ALTER TABLE `location` DROP COLUMN `plot_role`"))
        logger.info("[Migration] 已删除 location.plot_role")
