"""add video workflow last write id

Revision ID: 20261008_add_video_workflow_last
Revises: 20260926_users_remark_nick
Create Date: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261008_add_video_workflow_last'
down_revision: Union[str, None] = '20260926_users_remark_nick'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn) -> bool:
    count = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'video_workflow'
          AND COLUMN_NAME = 'last_write_id'
    """)).scalar()
    return bool(count)


def upgrade() -> None:
    """video_workflow 增加 last_write_id：本页写请求的身份，不参与内容哈希"""
    conn = op.get_bind()
    if _column_exists(conn):
        logger.info("[Migration] video_workflow.last_write_id 已存在，跳过")
        return
    conn.execute(text("""
        ALTER TABLE `video_workflow`
        ADD COLUMN `last_write_id` varchar(64) DEFAULT NULL
        COMMENT '最近一次成功写入的客户端写 id；不参与内容哈希'
        AFTER `content_version`
    """))
    logger.info("[Migration] video_workflow 新增 last_write_id 列")


def downgrade() -> None:
    """回滚：删除 last_write_id 列"""
    conn = op.get_bind()
    if not _column_exists(conn):
        logger.info("[Migration] video_workflow.last_write_id 不存在，跳过回滚")
        return
    conn.execute(text("ALTER TABLE `video_workflow` DROP COLUMN `last_write_id`"))
    logger.info("[Migration] 回滚：移除 video_workflow.last_write_id 列")
