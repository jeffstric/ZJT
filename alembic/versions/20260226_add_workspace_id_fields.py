"""add_workspace_id_fields

Revision ID: 20260226_workspace
Revises: dba3eea917cf
Create Date: 2026-02-26 18:15:00.000000+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260226_workspace'
down_revision: Union[str, None] = 'dba3eea917cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库：为 world 和 video_workflow 表预留 workspace_id 字段"""
    
    # 为 world 表添加 workspace_id 字段
    op.execute("""
        ALTER TABLE `world` 
        ADD COLUMN `workspace_id` INT DEFAULT NULL COMMENT '预留：所属工作空间ID'
    """)
    
    # 为 video_workflow 表添加 workspace_id 字段
    op.execute("""
        ALTER TABLE `video_workflow` 
        ADD COLUMN `workspace_id` INT DEFAULT NULL COMMENT '预留：所属工作空间ID'
    """)
    
    # 添加索引以提升后续查询性能
    op.execute("""
        ALTER TABLE `world` 
        ADD INDEX `idx_workspace` (`workspace_id`)
    """)
    
    op.execute("""
        ALTER TABLE `video_workflow` 
        ADD INDEX `idx_workspace` (`workspace_id`)
    """)


def downgrade() -> None:
    """回滚数据库：删除 workspace_id 字段"""
    
    # 删除索引
    op.execute("ALTER TABLE `world` DROP INDEX `idx_workspace`")
    op.execute("ALTER TABLE `video_workflow` DROP INDEX `idx_workspace`")
    
    # 删除字段
    op.execute("ALTER TABLE `world` DROP COLUMN `workspace_id`")
    op.execute("ALTER TABLE `video_workflow` DROP COLUMN `workspace_id`")
