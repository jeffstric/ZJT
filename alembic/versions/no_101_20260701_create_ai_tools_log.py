"""Create ai_tools_log table

新建 ai_tools_log 表，记录每个 ai_tools 任务的全生命周期事件（只增不改），
用于排查任务耗时、轮询静默、卡死等问题。

Revision ID: 20260701_ai_tools_log
Revises: 20260624_marketing_publications
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260701_ai_tools_log'
down_revision: Union[str, None] = '20260624_marketing_publications'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    """Check if a table exists"""
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table"
    ), {"table": table})
    return result.scalar() > 0


def upgrade() -> None:
    """Create ai_tools_log table"""
    conn = op.get_bind()

    if _table_exists(conn, 'ai_tools_log'):
        logger.info("Table ai_tools_log already exists, skipping")
        return

    conn.execute(text("""
        CREATE TABLE `ai_tools_log` (
          `id` bigint NOT NULL AUTO_INCREMENT,
          `ai_tool_id` int NOT NULL COMMENT '关联 ai_tools.id',
          `user_id` int DEFAULT NULL COMMENT '冗余 user_id，便于按用户排查',
          `project_id` varchar(100) DEFAULT NULL COMMENT '冗余上游任务ID（Duomi 等），可直接定位',
          `event_type` varchar(48) NOT NULL COMMENT '事件类型，见 AIToolsLogEvent',
          `status_from` tinyint DEFAULT NULL COMMENT '变更前 ai_tools.status',
          `status_to` tinyint DEFAULT NULL COMMENT '变更后 ai_tools.status',
          `implementation` int DEFAULT NULL COMMENT '冗余实现方ID',
          `try_count` int DEFAULT NULL COMMENT '冗余重试次数',
          `message` varchar(500) DEFAULT NULL COMMENT '简短描述',
          `detail` json DEFAULT NULL COMMENT '详细上下文（上游响应/URL/耗时等）',
          `duration_ms` int DEFAULT NULL COMMENT '本事件耗时(毫秒)，如下载/上传耗时',
          `create_at` timestamp(3) NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '事件发生时间(毫秒精度)',
          PRIMARY KEY (`id`),
          KEY `idx_atool_create` (`ai_tool_id`,`create_at`),
          KEY `idx_project_id` (`project_id`),
          KEY `idx_event_create` (`event_type`,`create_at`),
          KEY `idx_create_at` (`create_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI工具任务事件日志（只增不改，排查用）'
    """))
    logger.info("[Migration] Created ai_tools_log table")


def downgrade() -> None:
    """Drop ai_tools_log table"""
    conn = op.get_bind()
    if _table_exists(conn, 'ai_tools_log'):
        conn.execute(text("DROP TABLE `ai_tools_log`"))
        logger.info("[Migration] Dropped ai_tools_log table")
