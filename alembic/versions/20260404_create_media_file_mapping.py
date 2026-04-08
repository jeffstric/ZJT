"""create media_file_mapping table

Revision ID: 20260404_create_media
Revises: 20260402_multi_ref
Create Date: 2026-04-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260404_create_media'
down_revision: Union[str, None] = '20260407_000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 创建 media_file_mapping 表
    op.create_table('media_file_mapping',
        sa.Column('id', sa.Integer(), nullable=False, comment='主键ID'),
        sa.Column('user_id', sa.Integer(), nullable=True, comment='用户ID'),
        sa.Column('local_path', sa.String(1000), nullable=False, comment='本地文件相对路径'),
        sa.Column('cloud_path', sa.String(500), nullable=True, comment='云端存储路径'),
        sa.Column('policy_code', sa.String(50), nullable=False, default='media_cache', comment='策略代码'),
        sa.Column('source_type', sa.String(50), nullable=False, comment='来源类型'),
        sa.Column('source_id', sa.String(100), nullable=True, comment='来源ID'),
        sa.Column('media_type', sa.String(20), nullable=False, comment='媒体类型'),
        sa.Column('original_url', sa.String(1000), nullable=True, comment='原始URL'),
        sa.Column('file_size', sa.BigInteger(), nullable=True, comment='文件大小'),
        sa.Column('status', sa.String(20), nullable=True, default='active', comment='状态'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('local_path')
    )

    # 创建索引
    op.create_index('idx_user_id', 'media_file_mapping', ['user_id'])
    op.create_index('idx_cloud_path', 'media_file_mapping', ['cloud_path'])
    op.create_index('idx_source', 'media_file_mapping', ['source_type', 'source_id'])
    op.create_index('idx_policy_code', 'media_file_mapping', ['policy_code'])
    op.create_index('idx_status', 'media_file_mapping', ['status'])
    op.create_index('idx_media_type', 'media_file_mapping', ['media_type'])



def downgrade() -> None:
    op.drop_index('idx_media_type', table_name='media_file_mapping')
    op.drop_index('idx_status', table_name='media_file_mapping')
    op.drop_index('idx_policy_code', table_name='media_file_mapping')
    op.drop_index('idx_source', table_name='media_file_mapping')
    op.drop_index('idx_cloud_path', table_name='media_file_mapping')
    op.drop_index('idx_user_id', table_name='media_file_mapping')
    op.drop_table('media_file_mapping')
