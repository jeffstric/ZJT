"""Add audio_embedded column to storyboard_scene

Revision ID: 20260713_scene_audio_embed
Revises: 20260707_scene_diff_act
Create Date: 2026-07-13

为 storyboard_scene 新增「声音同出」字段：
- audio_embedded: TINYINT(1) NOT NULL DEFAULT 0
  含义：该分镜的选中视频已内嵌对话声音，导出完整视频时保留视频原音轨、
  跳过 TTS 配音混入。digital_human 分镜默认为 1（LTX2.3 产物已含口型音轨）。
回填：已存在的 video_type='digital_human' 分镜统一置 1。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# 注意：revision 字符串长度必须 ≤ 32 字符（alembic_version.version_num 为 varchar(32)）
revision: str = '20260713_scene_audio_embed'
down_revision: Union[str, None] = '20260707_scene_diff_act'
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

    if not _column_exists(conn, "storyboard_scene", "audio_embedded"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` "
            "ADD COLUMN `audio_embedded` TINYINT(1) NOT NULL DEFAULT 0 "
            "COMMENT '声音同出：选中视频已内嵌对话声音，导出完整视频时不混入TTS；digital_human 默认1' "
            "AFTER `video_type`"
        ))
        logger.info("[Migration] Added column storyboard_scene.audio_embedded")
    else:
        logger.info("[Migration] storyboard_scene.audio_embedded 已存在，跳过")

    # 回填存量数字人分镜：LTX2.3 产物已含口型音轨，导出时不应再混 TTS。
    updated = conn.execute(text(
        "UPDATE `storyboard_scene` SET `audio_embedded` = 1 "
        "WHERE `video_type` = 'digital_human' AND `audio_embedded` = 0"
    ))
    logger.info("[Migration] 回填 digital_human 分镜 audio_embedded=1，影响行数: %s",
                updated.rowcount if hasattr(updated, 'rowcount') else 'unknown')


def downgrade() -> None:
    conn = op.get_bind()

    if _column_exists(conn, "storyboard_scene", "audio_embedded"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` DROP COLUMN `audio_embedded`"
        ))
        logger.info("[Migration] Dropped column storyboard_scene.audio_embedded")
