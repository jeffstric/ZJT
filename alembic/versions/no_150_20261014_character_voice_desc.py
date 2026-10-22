"""character voice desc

角色表新增 voice_desc 字段：角色声学音色指纹文本（由"生成参考音频"链路的
LLM 音色分析自动写入，用户可在 script_writer 角色编辑页修改）。仅 MiniMax H3
（KFRef / Ref2VA）把它作为提示词原料渲染说话角色的声音描述，其他模型零变化。

Revision ID: 20261014_character_voice_desc
Revises: 20261013_add_preset_reference_vo
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261014_character_voice_desc'
down_revision: Union[str, None] = '20261013_add_preset_reference_vo'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # 幂等：字段已存在时跳过
    exists = conn.execute(text(
        "SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = 'character' "
        "AND COLUMN_NAME = 'voice_desc'"
    )).fetchone()
    if exists and exists.cnt:
        logger.info("column character.voice_desc already exists, skip")
        return
    conn.execute(text(
        "ALTER TABLE `character` "
        "ADD COLUMN `voice_desc` varchar(1000) CHARACTER SET utf8mb4 "
        "COLLATE utf8mb4_unicode_ci DEFAULT NULL "
        "COMMENT '音色描述（声学指纹文本，AI 按角色人设生成、用户可改，仅 MiniMax H3 提示词使用）' "
        "AFTER `default_voice`"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(text(
        "SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = 'character' "
        "AND COLUMN_NAME = 'voice_desc'"
    )).fetchone()
    if not exists or not exists.cnt:
        return
    conn.execute(text("ALTER TABLE `character` DROP COLUMN `voice_desc`"))
