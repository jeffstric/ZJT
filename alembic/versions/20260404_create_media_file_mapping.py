"""create media_file_mapping table

Revision ID: 20260404_create_media
Revises: 20260402_multi_ref
Create Date: 2026-04-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '20260404_create_media'
down_revision: Union[str, None] = '20260402_multi_ref'
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

    # 初始化现有数据（从 character/location/props 表导入）
    # character.reference_image
    op.execute(text("""
        INSERT INTO media_file_mapping (user_id, local_path, policy_code, source_type, source_id, media_type, original_url, status)
        SELECT DISTINCT
            user_id,
            SUBSTRING_INDEX(reference_image, '/upload/', -1) as local_path,
            'never_expire' as policy_code,
            'api' as source_type,
            CONCAT('character_', id) as source_id,
            'image' as media_type,
            reference_image as original_url,
            'active' as status
        FROM `character`
        WHERE reference_image IS NOT NULL AND reference_image != ''
        AND reference_image LIKE '/upload/%'
        ON DUPLICATE KEY UPDATE local_path = VALUES(local_path)
    """))

    # character.reference_images (JSON 数组)
    op.execute(text("""
        INSERT INTO media_file_mapping (user_id, local_path, policy_code, source_type, source_id, media_type, original_url, status)
        SELECT DISTINCT
            c.user_id,
            JSON_UNQUOTE(JSON_EXTRACT(r.value, '$.local_path')) as local_path,
            'never_expire' as policy_code,
            'api' as source_type,
            CONCAT('character_', c.id) as source_id,
            'image' as media_type,
            JSON_UNQUOTE(JSON_EXTRACT(r.value, '$.url')) as original_url,
            'active' as status
        FROM `character` c,
        JSON_TABLE(reference_images, '$[*]' COLUMNS (value JSON PATH '$')) as r
        WHERE reference_images IS NOT NULL
        AND JSON_UNQUOTE(JSON_EXTRACT(r.value, '$.local_path')) IS NOT NULL
        AND JSON_UNQUOTE(JSON_EXTRACT(r.value, '$.local_path')) LIKE '/upload/%'
        ON DUPLICATE KEY UPDATE local_path = VALUES(local_path)
    """))

    # location.reference_image
    op.execute(text("""
        INSERT INTO media_file_mapping (user_id, local_path, policy_code, source_type, source_id, media_type, original_url, status)
        SELECT DISTINCT
            user_id,
            SUBSTRING_INDEX(reference_image, '/upload/', -1) as local_path,
            'never_expire' as policy_code,
            'api' as source_type,
            CONCAT('location_', id) as source_id,
            'image' as media_type,
            reference_image as original_url,
            'active' as status
        FROM location
        WHERE reference_image IS NOT NULL AND reference_image != ''
        AND reference_image LIKE '/upload/%'
        ON DUPLICATE KEY UPDATE local_path = VALUES(local_path)
    """))

    # location.reference_images (JSON 数组)
    op.execute(text("""
        INSERT INTO media_file_mapping (user_id, local_path, policy_code, source_type, source_id, media_type, original_url, status)
        SELECT DISTINCT
            l.user_id,
            JSON_UNQUOTE(JSON_EXTRACT(r.value, '$.local_path')) as local_path,
            'never_expire' as policy_code,
            'api' as source_type,
            CONCAT('location_', l.id) as source_id,
            'image' as media_type,
            JSON_UNQUOTE(JSON_EXTRACT(r.value, '$.url')) as original_url,
            'active' as status
        FROM location l,
        JSON_TABLE(reference_images, '$[*]' COLUMNS (value JSON PATH '$')) as r
        WHERE reference_images IS NOT NULL
        AND JSON_UNQUOTE(JSON_EXTRACT(r.value, '$.local_path')) IS NOT NULL
        AND JSON_UNQUOTE(JSON_EXTRACT(r.value, '$.local_path')) LIKE '/upload/%'
        ON DUPLICATE KEY UPDATE local_path = VALUES(local_path)
    """))

    # props.reference_image
    op.execute(text("""
        INSERT INTO media_file_mapping (user_id, local_path, policy_code, source_type, source_id, media_type, original_url, status)
        SELECT DISTINCT
            user_id,
            SUBSTRING_INDEX(reference_image, '/upload/', -1) as local_path,
            'never_expire' as policy_code,
            'api' as source_type,
            CONCAT('props_', id) as source_id,
            'image' as media_type,
            reference_image as original_url,
            'active' as status
        FROM props
        WHERE reference_image IS NOT NULL AND reference_image != ''
        AND reference_image LIKE '/upload/%'
        ON DUPLICATE KEY UPDATE local_path = VALUES(local_path)
    """))


def downgrade() -> None:
    op.drop_index('idx_media_type', table_name='media_file_mapping')
    op.drop_index('idx_status', table_name='media_file_mapping')
    op.drop_index('idx_policy_code', table_name='media_file_mapping')
    op.drop_index('idx_source', table_name='media_file_mapping')
    op.drop_index('idx_cloud_path', table_name='media_file_mapping')
    op.drop_index('idx_user_id', table_name='media_file_mapping')
    op.drop_table('media_file_mapping')
