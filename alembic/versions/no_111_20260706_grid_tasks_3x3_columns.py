"""grid_image_tasks 新增 3x3 九宫格与 i2i 参考图相关列

Revision ID: 20260706_grid_3x3_cols
Revises: 20260706_dialogue_audio_duration
Create Date: 2026-07-06

新增列：
  - grid_size TINYINT DEFAULT 4          宫格总数（4=2x2, 9=3x3）
  - grid_layout VARCHAR(8) DEFAULT '2x2' 布局描述
  - item_names_json JSON NULL            结构化名称列表（9 名拼接可能超 varchar(255)）
  - target_entity_ids_json JSON NULL     切图回写目标 DB id 列表（强制按 id 回写，不再按名）
  - reference_images TEXT NULL           i2i 参考图列表 JSON（[{url, role_description}, ...]，
                                        每项含角色说明，用于宫格图生图与重试复原）

向后兼容：旧记录 grid_size 取默认 4，grid_layout 取默认 '2x2'。
若旧迁移已建 parent_reference_image(varchar)，本迁移会重命名为 reference_images(text)。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260706_grid_3x3_cols'
down_revision: Union[str, None] = '20260706_dialogue_audio_duration'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：为 grid_image_tasks 新增九宫格 + i2i 参考图相关列。"""
    conn = op.get_bind()

    existing_cols = {
        row[0] for row in conn.execute(text(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'grid_image_tasks'"
        ))
    }

    # 兼容旧迁移：若 parent_reference_image 已存在，重命名为 reference_images 并改 TEXT
    if "parent_reference_image" in existing_cols and "reference_images" not in existing_cols:
        logger.info("[Migration] 检测到旧列 parent_reference_image，重命名为 reference_images 并改为 TEXT")
        conn.execute(text(
            "ALTER TABLE `grid_image_tasks` "
            "CHANGE COLUMN `parent_reference_image` `reference_images` TEXT NULL "
            "COMMENT 'i2i 参考图列表 JSON [{url, role_description}, ...]'"
        ))
        existing_cols.add("reference_images")
        existing_cols.discard("parent_reference_image")

    columns_to_add = [
        ("grid_size", "TINYINT NOT NULL DEFAULT 4 COMMENT '宫格总数 (4=2x2, 9=3x3)'", "image_size"),
        ("grid_layout", "VARCHAR(8) NOT NULL DEFAULT '2x2' COMMENT '宫格布局 (2x2/3x3)'", "grid_size"),
        ("item_names_json", "JSON NULL COMMENT '结构化名称列表（避免逗号拼接歧义）'", "item_name"),
        ("target_entity_ids_json", "JSON NULL COMMENT '切图回写目标 DB id 列表（按 id 回写）'", "item_names_json"),
        ("reference_images", "TEXT NULL COMMENT 'i2i 参考图列表 JSON [{url, role_description}, ...]'", "target_entity_ids_json"),
    ]

    for col_name, col_def, after_col in columns_to_add:
        if col_name in existing_cols:
            logger.info(f"[Migration] 列 {col_name} 已存在，跳过")
            continue
        sql = f"ALTER TABLE `grid_image_tasks` ADD COLUMN `{col_name}` {col_def} AFTER `{after_col}`"
        conn.execute(text(sql))
        logger.info(f"[Migration] 已添加列 {col_name}")


def downgrade() -> None:
    """回滚：移除九宫格 + i2i 参考图相关列。"""
    conn = op.get_bind()

    existing_cols = {
        row[0] for row in conn.execute(text(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'grid_image_tasks'"
        ))
    }

    for col_name in [
        "reference_images",
        "target_entity_ids_json",
        "item_names_json",
        "grid_layout",
        "grid_size",
    ]:
        if col_name in existing_cols:
            conn.execute(text(f"ALTER TABLE `grid_image_tasks` DROP COLUMN `{col_name}`"))
            logger.info(f"[Migration] 已移除列 {col_name}")
