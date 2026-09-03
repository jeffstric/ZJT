"""merge_heads: 合并 ds_vision_peak_valley 与 uk_model_name 双 head

Revision ID: 20260901_merge_ds_heads
Revises: 20260901_ds_vision_peak_valley, 20260901_uk_model_name
Create Date: 2026-09-01

背景：develop_f723 的 no_124（uk_model_name）与 develop_f724 的 no_123
（ds_vision_peak_valley）曾并行挂到 20260901_fix_ds_vision_data（no_122），
且同号 no_123，导致 Multiple heads、启动时 alembic upgrade head 整体报错。
按 no_ 单头约定：uk_model_name 已改名 no_124（revision id 不变），
本迁移仅合并两条分支，无 schema/数据变更。

develop 既有顺序（旧→新）：
1. 20260901_ds_vision_peak_valley  ← develop_f724（峰谷计费，在前）
2. 20260901_uk_model_name          ← develop_f723（唯一索引，在后）
"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = "20260901_merge_ds_heads"
down_revision: Union[str, Sequence[str], None] = (
    "20260901_ds_vision_peak_valley",  # develop_f724 在前
    "20260901_uk_model_name",  # develop_f723 在后
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """合并迁移：无 schema 变更"""
    pass


def downgrade() -> None:
    """合并迁移：无 schema 变更"""
    pass
