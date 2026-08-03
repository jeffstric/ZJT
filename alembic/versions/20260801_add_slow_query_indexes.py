"""add_slow_query_indexes

补缺失索引，消除 cleanup/启动类批量 SQL 的全表扫描（8·1 端口耗尽事故后续优化）。

经排查 model/ + task/ 全部批量 SQL，仅以下两处 WHERE 字段无可用索引：

1. tasks 表 status：UPDATE tasks SET status=? WHERE status=?
   （model/tasks.py:430 reset_status，服务启动时 _reset_orphan_sync_tasks 调用）
   - 现有索引 idx_tasks_task_type(task_type, status) 因最左前缀 task_type 不在 WHERE 中而失效
   - 补 idx_status(status)

2. agent_tasks 表 created_at：DELETE FROM agent_tasks WHERE status IN(...) AND created_at<?
   （model/agent_tasks.py:365 delete_old_tasks，每 6h cleanup_agent_tasks 调用）
   - created_at 无独立索引
   - 补 idx_created_at(created_at)

其余清理表（agent_task_messages / chat_sessions / agent_verifications）经核实索引齐全，不动。
单列索引即可消除全表扫描（按时间/状态快速定位再回表），不引入复合索引复杂度。

Revision ID: 20260801_slow_query_idx
Revises: 20260722_agent_media_ctx
Create Date: 2026-08-01
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic. revision 必须 <= 32 字符（alembic_version.version_num 为 varchar(32)）
revision: str = '20260801_slow_query_idx'
down_revision: Union[str, None] = '20260722_agent_media_ctx'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def _index_exists(conn, table: str, index: str) -> bool:
    """检查索引是否已存在（幂等预检，参考 no_116_20260713 模板）"""
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :index"
    ), {"table": table, "index": index})
    return result.scalar() > 0


def upgrade() -> None:
    conn = op.get_bind()

    # 1. tasks.status：消除启动时 reset_status 的全表 UPDATE
    if not _index_exists(conn, 'tasks', 'idx_status'):
        op.create_index('idx_status', 'tasks', ['status'])
        logger.info("Created index idx_status on tasks(status)")
    else:
        logger.info("Index idx_status on tasks already exists, skipping")

    # 2. agent_tasks.created_at：消除每 6h cleanup DELETE 的全表扫描
    if not _index_exists(conn, 'agent_tasks', 'idx_created_at'):
        op.create_index('idx_created_at', 'agent_tasks', ['created_at'])
        logger.info("Created index idx_created_at on agent_tasks(created_at)")
    else:
        logger.info("Index idx_created_at on agent_tasks already exists, skipping")


def downgrade() -> None:
    conn = op.get_bind()

    if _index_exists(conn, 'agent_tasks', 'idx_created_at'):
        op.drop_index('idx_created_at', table_name='agent_tasks')
        logger.info("Dropped index idx_created_at on agent_tasks")

    if _index_exists(conn, 'tasks', 'idx_status'):
        op.drop_index('idx_status', table_name='tasks')
        logger.info("Dropped index idx_status on tasks")
