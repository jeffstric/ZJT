"""add announcements popup flag

Revision ID: 20261111_add_announcements_popup
Revises: 20261111_reset_users_terms_agree
Create Date: 2026-11-11
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261111_add_announcements_popup'
down_revision: Union[str, None] = '20261111_reset_users_terms_agree'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """announcements 表新增 popup 字段（弹窗通知标记）。

    popup=1 的已发布公告，用户端在页面加载时强弹窗展示（区别于铃铛面板的被动
    通知）；已读状态复用现有 announcement_reads per-user 表，标记已读后不再弹。
    首个使用场景：AIGC 内容标识规则变更预告（2026-11-11）。
    幂等：重复执行前先判断列是否存在。
    """
    conn = op.get_bind()
    row = conn.execute(text(
        "SELECT COUNT(*) AS c FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = 'announcements' "
        "AND column_name = 'popup'"
    )).fetchone()
    if row and row.c:
        logger.info("[Migration] announcements.popup 已存在，跳过")
        return
    op.execute("""
        ALTER TABLE `announcements`
        ADD COLUMN `popup` TINYINT NOT NULL DEFAULT 0
        COMMENT '弹窗通知（1=进页时强弹窗展示，已读后不再弹；0=仅铃铛面板）'
        AFTER `level`
    """)
    logger.info("[Migration] added announcements.popup column")


def downgrade() -> None:
    """回滚：删除 popup 列"""
    op.execute("ALTER TABLE `announcements` DROP COLUMN `popup`")
    logger.info("[Migration] dropped announcements.popup column")
