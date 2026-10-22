"""voice voice desc

voice 表（音色库）新增 voice_desc 字段：预置音色的独立声学音色指纹。
由音频理解模型（mimo-v2.6-pro）实际听预置样本生成——同 style 分类的音色
听感各异，模板表统一文案会让文字指纹失去区分度（用户实测反馈）。
角色选择音色库音色时，preset-voice 接口优先返回音色自己的指纹。

Revision ID: 20261016_voice_voice_desc
Revises: 20261014_character_voice_desc
Create Date: 2026-10-16
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261016_voice_voice_desc'
down_revision: Union[str, None] = '20261014_character_voice_desc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(text(
        "SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = 'voice' "
        "AND COLUMN_NAME = 'voice_desc'"
    )).fetchone()
    if exists and exists.cnt:
        logger.info("column voice.voice_desc already exists, skip")
        return
    conn.execute(text(
        "ALTER TABLE `voice` "
        "ADD COLUMN `voice_desc` varchar(1000) CHARACTER SET utf8mb4 "
        "COLLATE utf8mb4_unicode_ci DEFAULT NULL "
        "COMMENT '声学音色指纹（音频理解模型听预置样本生成，角色选用该音色时作为文字指纹）' "
        "AFTER `description`"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(text(
        "SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = 'voice' "
        "AND COLUMN_NAME = 'voice_desc'"
    )).fetchone()
    if not exists or not exists.cnt:
        return
    conn.execute(text("ALTER TABLE `voice` DROP COLUMN `voice_desc`"))
