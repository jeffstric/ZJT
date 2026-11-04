"""computing_power_log.transaction_id 改为唯一索引

退款、差额结算都用 transaction_id 做幂等键。原先只有非唯一索引，
并发的两次入账可以同时通过存在性检查。本迁移先把空串和重复流水收成
可建唯一索引的状态（保留最小 id 的那条，其余流水号清空并记入 note），
再创建 uk_transaction_id。重复行改成 NULL 后不在 downgrade 里还原。

Revision ID: 20261104_uk_power_log_txn
Revises: no_161_ai_tools_cancel_req
Create Date: 2026-11-04
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

revision: str = '20261104_uk_power_log_txn'
down_revision: Union[str, None] = 'no_161_ai_tools_cancel_req'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(conn, table: str, index: str) -> bool:
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :index"
    ), {"table": table, "index": index})
    return result.scalar() > 0


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(text(
        "UPDATE computing_power_log SET transaction_id = NULL "
        "WHERE transaction_id = ''"
    ))

    # 同一连接上重试 upgrade 时，上次失败可能留下这张临时表。
    conn.execute(text("DROP TEMPORARY TABLE IF EXISTS tmp_power_log_dup_ids"))
    conn.execute(text("""
        CREATE TEMPORARY TABLE tmp_power_log_dup_ids AS
        SELECT c.id AS id, c.transaction_id AS transaction_id
        FROM computing_power_log c
        INNER JOIN (
            SELECT transaction_id, MIN(id) AS keep_id
            FROM computing_power_log
            WHERE transaction_id IS NOT NULL
            GROUP BY transaction_id
            HAVING COUNT(*) > 1
        ) d ON c.transaction_id = d.transaction_id AND c.id <> d.keep_id
    """))
    dup_count = conn.execute(text("SELECT COUNT(*) FROM tmp_power_log_dup_ids")).scalar() or 0
    if dup_count:
        conn.execute(text("""
            UPDATE computing_power_log c
            INNER JOIN tmp_power_log_dup_ids d ON c.id = d.id
            SET c.note = LEFT(CONCAT(IFNULL(c.note, ''), ' [dup txn ', d.transaction_id, ']'), 500),
                c.transaction_id = NULL
        """))
        logger.info("[Migration] Cleared %s duplicate computing_power_log.transaction_id rows", dup_count)
    conn.execute(text("DROP TEMPORARY TABLE IF EXISTS tmp_power_log_dup_ids"))

    if not _index_exists(conn, "computing_power_log", "uk_transaction_id"):
        conn.execute(text(
            "ALTER TABLE computing_power_log "
            "ADD UNIQUE KEY uk_transaction_id (transaction_id)"
        ))
        logger.info("[Migration] Created unique index uk_transaction_id")
    else:
        logger.info("[Migration] uk_transaction_id already exists, skipping")

    if _index_exists(conn, "computing_power_log", "idx_transaction_id"):
        conn.execute(text("ALTER TABLE computing_power_log DROP INDEX idx_transaction_id"))
        logger.info("[Migration] Dropped redundant index idx_transaction_id")


def downgrade() -> None:
    conn = op.get_bind()
    if _index_exists(conn, "computing_power_log", "uk_transaction_id"):
        conn.execute(text("ALTER TABLE computing_power_log DROP INDEX uk_transaction_id"))
        logger.info("[Migration] Dropped unique index uk_transaction_id")
    if not _index_exists(conn, "computing_power_log", "idx_transaction_id"):
        conn.execute(text(
            "ALTER TABLE computing_power_log ADD INDEX idx_transaction_id (transaction_id)"
        ))
        logger.info("[Migration] Restored non-unique index idx_transaction_id")
