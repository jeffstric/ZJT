"""computing_power_log.transaction_id 加索引

Grok 多供应商切换退费事故修复（2026-08-19）：

退费改为按 ai_tools.transaction_id 关联扣费流水原额退还（消除
「按多米扣16分、按ZJTapi退80分」的扣返不一致）。本迁移为
computing_power_log.transaction_id 补单列索引，消除
get_deducted_power_by_transaction / check_transaction_exists
按流水号查询的全表扫描。

Revision ID: 20260819_txn_idx
Revises: 20260813_vm_period
Create Date: 2026-08-19

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic. revision 必须 <= 32 字符（alembic_version.version_num 为 varchar(32)）
revision: str = '20260819_txn_idx'
down_revision: Union[str, None] = '20260813_vm_period'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(conn, table: str, index: str) -> bool:
    """检查索引是否已存在（幂等预检，参考 no_117_20260801 模板）"""
    result = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND INDEX_NAME = :index"
    ), {"table": table, "index": index})
    return result.scalar() > 0


def upgrade() -> None:
    conn = op.get_bind()

    # computing_power_log.transaction_id：退费按扣费流水原额退还的查询索引
    if not _index_exists(conn, 'computing_power_log', 'idx_transaction_id'):
        op.create_index('idx_transaction_id', 'computing_power_log', ['transaction_id'])
        logger.info("Created index idx_transaction_id on computing_power_log(transaction_id)")
    else:
        logger.info("Index idx_transaction_id on computing_power_log already exists, skipping")


def downgrade() -> None:
    conn = op.get_bind()

    if _index_exists(conn, 'computing_power_log', 'idx_transaction_id'):
        op.drop_index('idx_transaction_id', table_name='computing_power_log')
        logger.info("Dropped index idx_transaction_id on computing_power_log")
