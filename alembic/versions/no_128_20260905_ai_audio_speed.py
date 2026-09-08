"""ai_audio 增加 speed 语速列

Revision ID: 20260905_ai_audio_speed
Revises: 20260905_add_mimo_models
Create Date: 2026-09-05
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260905_ai_audio_speed'
down_revision: Union[str, None] = '20260905_add_mimo_models'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """ai_audio 新增 speed 语速列（1.00 正常，>1 更快，<1 更慢，0.50~2.00）"""
    conn = op.get_bind()
    # MySQL 8 无 ADD COLUMN IF NOT EXISTS，用 information_schema 判断保证幂等
    exists = conn.execute(text(
        "SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = 'ai_audio' AND COLUMN_NAME = 'speed'"
    )).scalar()
    if not exists:
        conn.execute(text(
            "ALTER TABLE `ai_audio` "
            "ADD COLUMN `speed` decimal(4,2) NOT NULL DEFAULT '1.00' "
            "COMMENT '语速: 1.00正常, >1更快, <1更慢, 范围0.50~2.00（IndexTTS duration_factor=1/speed）' "
            "AFTER `message`"
        ))
        logger.info("[Migration] ai_audio 增加 speed 列")
    else:
        logger.info("[Migration] ai_audio.speed 列已存在，跳过")


def downgrade() -> None:
    """回滚：删除 ai_audio.speed 列"""
    conn = op.get_bind()
    exists = conn.execute(text(
        "SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = 'ai_audio' AND COLUMN_NAME = 'speed'"
    )).scalar()
    if exists:
        conn.execute(text("ALTER TABLE `ai_audio` DROP COLUMN `speed`"))
        logger.info("[Migration] ai_audio 删除 speed 列")
    else:
        logger.info("[Migration] ai_audio.speed 列不存在，跳过回滚")
