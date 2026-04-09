"""add qwen3.5-plus and qwen3.6-plus models

Revision ID: 20260407_qwen_models
Revises: 20260402_multi_ref
Create Date: 2026-04-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '20260407_qwen_models'
down_revision: Union[str, None] = '20260402_multi_ref'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 添加 qwen3.5-plus 模型
    op.execute(text("""
        INSERT INTO `model` (model_name, created_at, note)
        VALUES ('qwen3.5-plus', NOW(), 'Qwen 3.5 Plus - 阿里通义千问3.5 Plus版')
    """))

    # 添加 qwen3.6-plus 模型
    op.execute(text("""
        INSERT INTO `model` (model_name, created_at, note)
        VALUES ('qwen3.6-plus', NOW(), 'Qwen 3.6 Plus - 阿里通义千问3.6 Plus版')
    """))

    # 关联到 vendor (假设 vendor_id=1 是 jiekou)
    # qwen3.5-plus (model_id=3)
    op.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold)
        VALUES (1, 3, NOW(), 11000, 1800, 112000)
    """))

    # qwen3.6-plus (model_id=4)
    op.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold)
        VALUES (1, 4, NOW(), 11000, 1800, 112000)
    """))


def downgrade() -> None:
    # 删除 vendor_model 关联
    op.execute(text("DELETE FROM `vendor_model` WHERE model_id IN (3, 4)"))
    # 删除 model
    op.execute(text("DELETE FROM `model` WHERE model_name IN ('qwen3.5-plus', 'qwen3.6-plus')"))
