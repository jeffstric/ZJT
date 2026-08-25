"""merge_heads: 合并模块绑定与算力流水索引双 head

Revision ID: 20260821_merge_heads
Revises: 20260820_module_binding, 20260819_txn_idx
Create Date: 2026-08-21

develop_629b 的 user_module_task_binding 挂在 20260811_user_modules，
同时 develop 上 computing_power_log.transaction_id 索引是另一条 head，
启动 `alembic upgrade head` 会报 Multiple heads。本迁移仅合并分支。
"""
from typing import Sequence, Union


revision: str = "20260821_merge_heads"
down_revision: Union[str, Sequence[str], None] = (
    "20260820_module_binding",
    "20260819_txn_idx",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """合并迁移：无 schema 变更"""
    pass


def downgrade() -> None:
    """合并迁移：无回滚操作"""
    pass
