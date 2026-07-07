"""Add difficulty and act_name columns to storyboard_scene

Revision ID: 20260707_scene_diff_act
Revises: 20260706_scene_duration_decimal
Create Date: 2026-07-07

为 storyboard_scene 新增两个一等字段：
- difficulty: 分镜难易程度（易/中/难），由 LLM 综合判定，默认 '中'
- act_name: 所属幕/分镜组名称，源自 LLM shot_group.group_name（提升为独立列）
旧数据不回填：difficulty 由 DEFAULT '中' 兜底，act_name 保持 NULL。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# 注意：revision 字符串长度必须 ≤ 32 字符（alembic_version.version_num 为 varchar(32)）
revision: str = '20260707_scene_diff_act'
down_revision: Union[str, None] = '20260706_scene_duration_decimal'
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

    if not _column_exists(conn, "storyboard_scene", "difficulty"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` "
            "ADD COLUMN `difficulty` VARCHAR(8) NOT NULL DEFAULT '中' "
            "COMMENT '分镜难易程度: 易/中/难，见 SceneDifficulty' "
            "AFTER `video_config_json`"
        ))
        logger.info("[Migration] Added column storyboard_scene.difficulty")
    else:
        logger.info("[Migration] storyboard_scene.difficulty 已存在，跳过")

    if not _column_exists(conn, "storyboard_scene", "act_name"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` "
            "ADD COLUMN `act_name` VARCHAR(255) DEFAULT NULL "
            "COMMENT '所属幕/分镜组名称（源自 LLM shot_group.group_name）' "
            "AFTER `difficulty`"
        ))
        logger.info("[Migration] Added column storyboard_scene.act_name")
    else:
        logger.info("[Migration] storyboard_scene.act_name 已存在，跳过")


def downgrade() -> None:
    conn = op.get_bind()

    if _column_exists(conn, "storyboard_scene", "act_name"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` DROP COLUMN `act_name`"
        ))
        logger.info("[Migration] Dropped column storyboard_scene.act_name")

    if _column_exists(conn, "storyboard_scene", "difficulty"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` DROP COLUMN `difficulty`"
        ))
        logger.info("[Migration] Dropped column storyboard_scene.difficulty")
