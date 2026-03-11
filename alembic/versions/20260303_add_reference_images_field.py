"""add_reference_images_field

Revision ID: 20260303_ref_images
Revises: 20260302_google_llm
Create Date: 2026-03-03 10:00:00.000000+08:00

为 ai_tools 表添加 reference_images 字段，用于存储参考图URL列表（JSON格式）
支持三种图片模式：首尾帧模式、多参考图模式、首尾帧+参考图模式
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260303_ref_images'
down_revision: Union[str, None] = '20260302_google_llm'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库：为 ai_tools 表添加 reference_images 字段"""
    
    # 添加 reference_images 字段（TEXT类型，存储JSON数组）
    op.execute("""
        ALTER TABLE `ai_tools` 
        ADD COLUMN `reference_images` TEXT DEFAULT NULL COMMENT '参考图URL列表，JSON数组格式，如["url1","url2"]'
    """)


def downgrade() -> None:
    """回滚数据库：删除 reference_images 字段"""
    
    op.execute("ALTER TABLE `ai_tools` DROP COLUMN `reference_images`")
