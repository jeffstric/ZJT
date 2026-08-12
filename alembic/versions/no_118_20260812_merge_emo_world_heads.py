"""merge_heads: 合并 emo_vec 与 world soft-delete 双 head

Revision ID: 20260812_merge_heads
Revises: 20260812_dlg_emo_vec, 20260812_world_soft_del
Create Date: 2026-08-12

develop 既有顺序（旧→新）：
1. 20260812_dlg_emo_vec      ← 997705fa 对白情感向量（在前）
2. 20260812_world_soft_del   ← a95f9eff 世界伪删除（在后）

两条迁移曾并列挂到 20260810_add_agnes，导致 Multiple heads。
本迁移仅合并分支，无 schema/数据变更。
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = "20260812_merge_heads"
down_revision: Union[str, Sequence[str], None] = (
    "20260812_dlg_emo_vec",  # develop 在前
    "20260812_world_soft_del",  # develop 在后
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """合并迁移：无 schema 变更"""
    pass


def downgrade() -> None:
    """合并迁移：无回滚操作"""
    pass
