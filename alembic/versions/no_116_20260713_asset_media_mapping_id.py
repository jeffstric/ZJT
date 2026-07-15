"""Add media_mapping_id to storyboard_scene_asset

Revision ID: 20260713_asset_media_map
Revises: 20260714_script_split
Create Date: 2026-07-13

为 storyboard_scene_asset 新增 CDN 媒体映射字段：
- media_mapping_id: INT DEFAULT NULL，→ media_file_mapping.id
  含义：该资产生成的图片/视频已建立 CDN 映射（宫格拆分单图首帧接入图床分发，
  降低业务机带宽）。映射由 cdn_redirect_middleware 在访问 /upload/ 路径时
  查询并 302 重定向到七牛云签名 URL。
配套索引 idx_media_mapping_id 与外键 fk_asset_media_mapping_id。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# 注意：revision 字符串长度必须 ≤ 32 字符（alembic_version.version_num 为 varchar(32)）
revision: str = '20260713_asset_media_map'
down_revision: Union[str, None] = '20260714_script_split'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    return result.scalar() > 0


def _index_exists(conn, table: str, index: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :index"
    ), {"table": table, "index": index})
    return result.scalar() > 0


def _fk_exists(conn, table: str, fk: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table "
        "AND CONSTRAINT_NAME = :fk AND CONSTRAINT_TYPE = 'FOREIGN KEY'"
    ), {"table": table, "fk": fk})
    return result.scalar() > 0


def upgrade() -> None:
    conn = op.get_bind()
    table = "storyboard_scene_asset"

    if not _column_exists(conn, table, "media_mapping_id"):
        conn.execute(text(
            f"ALTER TABLE `{table}` "
            "ADD COLUMN `media_mapping_id` INT DEFAULT NULL "
            "COMMENT '→ media_file_mapping.id（CDN 媒体映射，用于图床分发降带宽）' "
            "AFTER `result_url`"
        ))
        logger.info("[Migration] Added column %s.media_mapping_id", table)
    else:
        logger.info("[Migration] %s.media_mapping_id 已存在，跳过", table)

    if not _index_exists(conn, table, "idx_media_mapping_id"):
        conn.execute(text(
            f"CREATE INDEX `idx_media_mapping_id` ON `{table}` (`media_mapping_id`)"
        ))
        logger.info("[Migration] Created index idx_media_mapping_id on %s", table)

    if not _fk_exists(conn, table, "fk_asset_media_mapping_id"):
        conn.execute(text(
            f"ALTER TABLE `{table}` "
            "ADD CONSTRAINT `fk_asset_media_mapping_id` "
            "FOREIGN KEY (`media_mapping_id`) REFERENCES `media_file_mapping`(`id`)"
        ))
        logger.info("[Migration] Created fk_asset_media_mapping_id on %s", table)


def downgrade() -> None:
    conn = op.get_bind()
    table = "storyboard_scene_asset"

    if _fk_exists(conn, table, "fk_asset_media_mapping_id"):
        conn.execute(text(
            f"ALTER TABLE `{table}` DROP FOREIGN KEY `fk_asset_media_mapping_id`"
        ))
        logger.info("[Migration] Dropped fk_asset_media_mapping_id on %s", table)

    if _index_exists(conn, table, "idx_media_mapping_id"):
        conn.execute(text(
            f"DROP INDEX `idx_media_mapping_id` ON `{table}`"
        ))
        logger.info("[Migration] Dropped index idx_media_mapping_id on %s", table)

    if _column_exists(conn, table, "media_mapping_id"):
        conn.execute(text(
            f"ALTER TABLE `{table}` DROP COLUMN `media_mapping_id`"
        ))
        logger.info("[Migration] Dropped column %s.media_mapping_id", table)
