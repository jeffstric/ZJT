"""add asset quota enabled column

asset_library_quota 增加 enabled 列：逐用户资产库使用权限开关。
配合 system_config 的 asset_library.allow_all_users：全员模式关闭时，
仅 enabled=1 的用户可使用资产库（见 docs/backend/asset_library.md §功能开关）。

Revision ID: 20261026_add_asset_quota_enabled
Revises: 20261024_add_asset_library_table
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261026_add_asset_quota_enabled'
down_revision: Union[str, None] = '20261024_add_asset_library_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """asset_library_quota 增加 enabled 列（幂等：information_schema 判断）。"""
    conn = op.get_bind()
    exists = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() "
        "AND table_name = 'asset_library_quota' AND column_name = 'enabled'"
    )).scalar()
    if not exists:
        conn.execute(text(
            "ALTER TABLE `asset_library_quota` "
            "ADD COLUMN `enabled` tinyint NOT NULL DEFAULT 0 "
            "COMMENT '是否允许使用资产库（allow_all_users 关闭时逐用户生效）' "
            "AFTER `used_bytes`"
        ))
        logger.info("[Migration] Added column asset_library_quota.enabled")
    else:
        logger.info("[Migration] Column asset_library_quota.enabled already exists, skip")


def downgrade() -> None:
    """回滚：删除 enabled 列（数据修复类回滚，权限开关信息随列丢弃）。"""
    conn = op.get_bind()
    exists = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() "
        "AND table_name = 'asset_library_quota' AND column_name = 'enabled'"
    )).scalar()
    if exists:
        conn.execute(text("ALTER TABLE `asset_library_quota` DROP COLUMN `enabled`"))
        logger.info("[Migration] Dropped column asset_library_quota.enabled")
