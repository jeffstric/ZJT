"""add asset group create index

asset_library 增加 idx_group_create(group_id, create_at) 复合索引：
@ 提及/浏览弹窗按分组目录懒加载资产时，组内按 create_at DESC, id DESC
分页（services.list_assets），此前仅有单列 idx_group（只过滤不免排序），
资产量大后每次翻页都触发 filesort。该索引使 group_id 等值过滤后直接
按 create_at 索引序读取，避免 filesort。

Revision ID: 20261027_add_asset_group_create
Revises: 20261026_add_asset_quota_enabled
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261027_add_asset_group_create'
down_revision: Union[str, None] = '20261026_add_asset_quota_enabled'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(conn, table: str, index: str) -> bool:
    return bool(conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() "
        f"AND table_name = '{table}' AND index_name = '{index}'"
    )).scalar())


def upgrade() -> None:
    """asset_library 增加 (group_id, create_at) 复合索引（幂等：information_schema 判断）。"""
    conn = op.get_bind()
    if not _index_exists(conn, 'asset_library', 'idx_group_create'):
        conn.execute(text(
            "ALTER TABLE `asset_library` "
            "ADD KEY `idx_group_create` (`group_id`, `create_at`)"
        ))
        logger.info("Added idx_group_create (group_id, create_at) to asset_library")


def downgrade() -> None:
    """回滚：删除 idx_group_create（纯索引，无数据变更）。"""
    conn = op.get_bind()
    if _index_exists(conn, 'asset_library', 'idx_group_create'):
        conn.execute(text("ALTER TABLE `asset_library` DROP KEY `idx_group_create`"))
