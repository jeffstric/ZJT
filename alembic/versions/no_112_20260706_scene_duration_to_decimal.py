"""storyboard_scene.duration / storyboard.total_duration 由 INT 改为 DECIMAL(10,3)

Revision ID: 20260706_scene_duration_decimal
Revises: 20260706_grid_3x3_cols
Create Date: 2026-07-06

背景：
  分镜下所有选中配音生成成功后，需要把 scene.duration 同步为这些音频 duration 的精确求和。
  音频时长经 ffprobe 探测为浮点秒，原 INT 会截断精度并可能短于音频实际时长（视频丢帧）。
  因此改为 DECIMAL(10,3)，保留毫秒级精度。

向后兼容：
  MySQL INT → DECIMAL 隐式转换安全，旧数据原样保留为整数值（如 5 → 5.000），不丢精度。
  应用层读取后按浮点处理；视频生成提交时统一 math.ceil 取整，确保不短于音频。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260706_scene_duration_decimal'
down_revision: Union[str, None] = '20260706_grid_3x3_cols'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_type_is_decimal(conn, table: str, column: str) -> bool:
    """判断指定列当前类型是否为 DECIMAL/NUMERIC（幂等保护，避免重复 MODIFY 报错）。"""
    result = conn.execute(text(
        "SELECT DATA_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :column"
    ), {"table": table, "column": column})
    row = result.fetchone()
    if not row:
        return False
    data_type = (row[0] or '').lower()
    return data_type in ('decimal', 'numeric')


def upgrade() -> None:
    """升级：duration / total_duration INT → DECIMAL(10,3)。"""
    conn = op.get_bind()

    if not _column_type_is_decimal(conn, "storyboard_scene", "duration"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` "
            "MODIFY COLUMN `duration` DECIMAL(10,3) DEFAULT 5.000 "
            "COMMENT '分镜时长（秒），音频全部完成时自动同步为选中配音求和（毫秒级精度）'"
        ))
        logger.info("[Migration] storyboard_scene.duration INT → DECIMAL(10,3)")
    else:
        logger.info("[Migration] storyboard_scene.duration 已为 DECIMAL，跳过")

    if not _column_type_is_decimal(conn, "storyboard", "total_duration"):
        conn.execute(text(
            "ALTER TABLE `storyboard` "
            "MODIFY COLUMN `total_duration` DECIMAL(10,3) DEFAULT 0.000 "
            "COMMENT '总时长（秒），由各分镜 duration 求和'"
        ))
        logger.info("[Migration] storyboard.total_duration INT → DECIMAL(10,3)")
    else:
        logger.info("[Migration] storyboard.total_duration 已为 DECIMAL，跳过")


def downgrade() -> None:
    """回滚：DECIMAL(10,3) → INT。

    注意：DECIMAL → INT 会按四舍五入截断小数，原浮点时长精度丢失（不可逆）。
    仅在确需回滚结构时使用。
    """
    conn = op.get_bind()

    if _column_type_is_decimal(conn, "storyboard_scene", "duration"):
        conn.execute(text(
            "ALTER TABLE `storyboard_scene` "
            "MODIFY COLUMN `duration` INT DEFAULT 5 COMMENT '分镜时长（秒）'"
        ))
        logger.info("[Migration] storyboard_scene.duration DECIMAL → INT（精度已截断）")

    if _column_type_is_decimal(conn, "storyboard", "total_duration"):
        conn.execute(text(
            "ALTER TABLE `storyboard` "
            "MODIFY COLUMN `total_duration` INT DEFAULT 0 COMMENT '总时长（秒）'"
        ))
        logger.info("[Migration] storyboard.total_duration DECIMAL → INT（精度已截断）")
