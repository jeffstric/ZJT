"""Add duration column to storyboard_dialogue_audio

Revision ID: 20260706_dialogue_audio_duration
Revises: 20260704_storyboard_img_batch
Create Date: 2026-07-06
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)


revision: str = '20260706_dialogue_audio_duration'
down_revision: Union[str, None] = '20260704_storyboard_img_batch'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    return result.scalar() > 0


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "storyboard_dialogue_audio", "duration"):
        conn.execute(text(
            "ALTER TABLE `storyboard_dialogue_audio` "
            "ADD COLUMN `duration` DECIMAL(10,3) DEFAULT NULL "
            "COMMENT '音频时长（秒），生成完成时由 ffprobe 探测写入' "
            "AFTER `audio_url`"
        ))
        logger.info("[Migration] Added column storyboard_dialogue_audio.duration")


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "storyboard_dialogue_audio", "duration"):
        conn.execute(text(
            "ALTER TABLE `storyboard_dialogue_audio` DROP COLUMN `duration`"
        ))
        logger.info("[Migration] Dropped column storyboard_dialogue_audio.duration")
