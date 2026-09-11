"""character source field

Revision ID: 20260911_character_source_field
Revises: 20260910_add_gpt_image_2_5_power
Create Date: 2026-09-11
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260911_character_source_field'
down_revision: Union[str, None] = '20260910_add_gpt_image_2_5_power'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 character 表新增 source 列，区分手动创建与剧本拆分自动入库的角色。"""
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name='character' AND column_name='source'"
    ))
    row = result.fetchone()
    count = row[0] if row else 0
    if count == 0:
        conn.execute(text(
            "ALTER TABLE `character` "
            "ADD COLUMN `source` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci "
            "NOT NULL DEFAULT 'manual' COMMENT '角色来源: manual=手动创建, script_split=剧本拆分自动入库' "
            "AFTER `sora_character`"
        ))
        logger.info("[Migration] character 表已新增 source 列（默认 manual）")
    else:
        logger.info("[Migration] character.source 已存在，跳过")


def downgrade() -> None:
    """回滚：删除 source 列（仅丢来源标记，不涉及业务数据）。"""
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name='character' AND column_name='source'"
    ))
    row = result.fetchone()
    count = row[0] if row else 0
    if count > 0:
        conn.execute(text("ALTER TABLE `character` DROP COLUMN `source`"))
        logger.info("[Migration] character 表已删除 source 列")
    else:
        logger.info("[Migration] character.source 不存在，跳过回滚")

