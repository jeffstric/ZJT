"""
添加实现方统计查询索引

为 ai_tools 表添加复合索引，优化实现方统计数据查询性能

Revision ID: 20260326_add_stats_index
Revises: 20260326_stats_cache
Create Date: 2026-03-26 12:33:00

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260326_add_stats_index'
down_revision = '20260326_stats_cache'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE INDEX idx_impl_type_status_create ON ai_tools 
        (implementation, type, status, create_time)
    """)


def downgrade():
    op.execute("""
        DROP INDEX idx_impl_type_status_create ON ai_tools
    """)
