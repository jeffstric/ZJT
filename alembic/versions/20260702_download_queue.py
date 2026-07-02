"""Create download_queue table

新建 download_queue 表，作为媒体下载队列，解耦 visual_task 主循环的秒级状态机推进
与分钟级 IO 下载。建表 SQL 与 model/download_queue.py 末尾 CREATE_TABLE_SQL 保持一致。

Revision ID: 20260702_download_queue
Revises: 20260701_ai_tools_log
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260702_download_queue'
down_revision: Union[str, None] = '20260701_ai_tools_log'
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
    """Create download_queue table"""
    conn = op.get_bind()

    if _table_exists(conn, 'download_queue'):
        logger.info("Table download_queue already exists, skipping")
        return

    # 与 model/download_queue.py 的 CREATE_TABLE_SQL 保持一致
    conn.execute(text("""
CREATE TABLE IF NOT EXISTS `download_queue` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `ai_tool_id` bigint NOT NULL COMMENT '关联 ai_tools.id（幂等去重键）',
  `task_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '冗余 task 标识(==ai_tool_id)，便于按 task 查',
  `project_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '冗余 project_id，worker 成功后按它更新 ai_tools',
  `remote_url` text COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '待下载的远端 URL（唯一真相源）',
  `media_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'video' COMMENT 'image/video',
  `status` tinyint NOT NULL DEFAULT '0' COMMENT '0=待处理 1=处理中 2=成功 -1=失败(已兜底COMPLETED)',
  `try_count` int NOT NULL DEFAULT '0' COMMENT '已尝试次数',
  `max_try` int NOT NULL DEFAULT '3' COMMENT '最大尝试次数，达上限后用 remote_url 兜底',
  `next_trigger` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '下次可被 claim 的时间（退避用）',
  `result_url` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '下载成功后的本地/CDN URL',
  `error_message` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '最近一次失败原因',
  `worker_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '抢占标记 hostname-pid（多实例防重）',
  `lease_until` datetime DEFAULT NULL COMMENT '租约到期时间；status=1 且到期则被回收',
  `create_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ai_tool_id` (`ai_tool_id`),
  KEY `idx_status_trigger` (`status`, `next_trigger`),
  KEY `idx_lease_until` (`status`, `lease_until`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='媒体下载队列：解耦主循环状态机推进与分钟级IO下载'
"""))
    logger.info("Created download_queue table")


def downgrade() -> None:
    """Drop download_queue table"""
    conn = op.get_bind()
    conn.execute(text("DROP TABLE IF EXISTS download_queue"))
