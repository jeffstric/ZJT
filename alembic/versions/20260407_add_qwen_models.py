"""add qwen3.5-plus and qwen3.6-plus models

Revision ID: 20260407_qwen_models
Revises: 20260409_tiered_billing
Create Date: 2026-04-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '20260407_qwen_models'
down_revision: Union[str, None] = '20260409_tiered_billing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 添加 aliyun vendor
    op.execute(text("""
        INSERT INTO `vendor` (vendor_name, created_at, note)
        VALUES ('aliyun', NOW(), '阿里云 - 通义千问')
    """))

    # 添加 qwen3.5-plus 模型
    op.execute(text("""
        INSERT INTO `model` (model_name, created_at, note)
        VALUES ('qwen3.5-plus', NOW(), '')
    """))

    # 添加 qwen3.6-plus 模型
    op.execute(text("""
        INSERT INTO `model` (model_name, created_at, note)
        VALUES ('qwen3.6-plus', NOW(), '')
    """))

    # 关联到 aliyun vendor，使用子查询获取正确的 vendor_id 和 model_id
    # qwen3.5-plus
    op.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold)
        SELECT v.id, m.id, NOW(), 11000, 1800, 112000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'aliyun' AND m.model_name = 'qwen3.5-plus'
    """))

    # qwen3.6-plus
    op.execute(text("""
        INSERT INTO `vendor_model` (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold)
        SELECT v.id, m.id, NOW(), 11000, 1800, 112000
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'aliyun' AND m.model_name = 'qwen3.6-plus'
    """))


def downgrade() -> None:
    # 删除 vendor_model 关联（通过子查询获取 model_id）
    op.execute(text("""
        DELETE FROM `vendor_model`
        WHERE model_id IN (SELECT id FROM `model` WHERE model_name IN ('qwen3.5-plus', 'qwen3.6-plus'))
    """))
    # 删除 model
    op.execute(text("DELETE FROM `model` WHERE model_name IN ('qwen3.5-plus', 'qwen3.6-plus')"))
    # 删除 aliyun vendor
    op.execute(text("DELETE FROM `vendor` WHERE vendor_name = 'aliyun'"))
