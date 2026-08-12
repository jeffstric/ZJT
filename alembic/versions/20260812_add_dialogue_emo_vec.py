"""storyboard_dialogue 增加 emo_vec 情感向量字段

仅企业版业务会写入/使用该字段；列对全版本存在，NULL 兼容。

Revision ID: 20260812_dlg_emo_vec
Revises: 20260810_add_agnes
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

revision: str = "20260812_dlg_emo_vec"
down_revision: Union[str, None] = "20260810_add_agnes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'storyboard_dialogue'
              AND COLUMN_NAME = 'emo_vec'
            """
        )
    ).scalar()
    if exists:
        logger.info("[Migration] storyboard_dialogue.emo_vec already exists, skip")
        return
    conn.execute(
        text(
            """
            ALTER TABLE `storyboard_dialogue`
            ADD COLUMN `emo_vec` VARCHAR(255) NULL
              COMMENT '情感向量(逗号分隔8维，与ai_audio.emo_vec一致；仅企业版使用)'
              AFTER `volume`
            """
        )
    )
    logger.info("[Migration] Added storyboard_dialogue.emo_vec")


def downgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'storyboard_dialogue'
              AND COLUMN_NAME = 'emo_vec'
            """
        )
    ).scalar()
    if not exists:
        logger.info("[Migration] storyboard_dialogue.emo_vec not present, skip drop")
        return
    conn.execute(text("ALTER TABLE `storyboard_dialogue` DROP COLUMN `emo_vec`"))
    logger.info("[Migration] Dropped storyboard_dialogue.emo_vec")
