"""add ai tools cancel requested

Revision ID: no_161_ai_tools_cancel_req
Revises: 20261101_storyboard_batch_job_li
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = 'no_161_ai_tools_cancel_req'
down_revision: Union[str, None] = '20261101_storyboard_batch_job_li'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """ai_tools.cancel_requested：预处理步骤已在执行时，取消只记标识，步骤结束后再终态化。"""
    conn = op.get_bind()
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'ai_tools'
          AND COLUMN_NAME = 'cancel_requested'
    """)).scalar()
    if not exists:
        conn.execute(text("""
            ALTER TABLE `ai_tools`
            ADD COLUMN `cancel_requested` TINYINT NOT NULL DEFAULT 0
            COMMENT '用户已请求取消（1）。预处理步骤在途时不立刻改终态、不退款'
            AFTER `status`
        """))
        logger.info("[Migration] ai_tools.cancel_requested 列已添加")
    else:
        logger.info("[Migration] ai_tools.cancel_requested 已存在，跳过 ADD COLUMN")


def downgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'ai_tools'
          AND COLUMN_NAME = 'cancel_requested'
    """)).scalar()
    if exists:
        conn.execute(text("ALTER TABLE `ai_tools` DROP COLUMN `cancel_requested`"))
        logger.info("[Migration] ai_tools.cancel_requested 已删除")
