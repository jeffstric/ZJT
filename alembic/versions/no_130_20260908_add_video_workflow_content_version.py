"""video_workflow 新增 content_version 列：PUT 乐观锁原子 CAS（替代 check-then-act）

Revision ID: 20260908_add_video_workflow_cont
Revises: 20260906_add_announcement_tables
Create Date: 2026-09-08
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260908_add_video_workflow_cont'
down_revision: Union[str, None] = '20260906_add_announcement_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """video_workflow 增加 content_version 列（服务端乐观锁版本号，每次内容更新 +1）"""
    conn = op.get_bind()
    conn.execute(text("""
        ALTER TABLE `video_workflow`
        ADD COLUMN `content_version` int NOT NULL DEFAULT 0
        COMMENT '内容乐观锁版本号：PUT 条件更新 WHERE 用，每次内容写入 +1'
        AFTER `workflow_data`
    """))
    logger.info("[Migration] video_workflow 新增 content_version 列（原子 CAS）")


def downgrade() -> None:
    """回滚：删除 content_version 列"""
    conn = op.get_bind()
    conn.execute(text("ALTER TABLE `video_workflow` DROP COLUMN `content_version`"))
    logger.info("[Migration] 回滚：移除 video_workflow.content_version 列")

