"""qwen 模型配置分段计费

为 qwen3.5-plus 和 qwen3.6-plus 配置分段计费：
- qwen3.5-plus: 3个档位 (0-128K, 128K-256K, >256K)
- qwen3.6-plus: 2个档位 (0-256K, >256K)

Revision ID: 20260409_qwen_tiered
Revises: 20260409_tiered_billing
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '20260409_qwen_tiered'
down_revision: Union[str, None] = '20260409_tiered_billing'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 获取 qwen3.5-plus 和 qwen3.6-plus 的 model_id
    result = conn.execute(text("SELECT id FROM model WHERE model_name = 'qwen3.5-plus'"))
    row = result.fetchone()
    qwen35_model_id = row[0] if row else None

    result = conn.execute(text("SELECT id FROM model WHERE model_name = 'qwen3.6-plus'"))
    row = result.fetchone()
    qwen36_model_id = row[0] if row else None

    if not qwen35_model_id or not qwen36_model_id:
        raise Exception("qwen3.5-plus 或 qwen3.6-plus 模型不存在，请先运行 20260407_add_qwen_models 迁移")

    # 删除现有的单一计费配置
    op.execute(text(f"""
        DELETE FROM vendor_model 
        WHERE vendor_id = 1 AND model_id IN ({qwen35_model_id}, {qwen36_model_id})
    """))

    # === qwen3.5-plus 分段计费配置 ===

    # 档位1: 0~128K (最便宜)
    op.execute(text(f"""
        INSERT INTO vendor_model
            (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        VALUES
            (1, {qwen35_model_id}, 50000, 8334, 500000, 128000)
    """))

    # 档位2: 128K~256K (中档)
    op.execute(text(f"""
        INSERT INTO vendor_model
            (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        VALUES
            (1, {qwen35_model_id}, 20000, 3334, 200000, 256000)
    """))

    # 档位3: >256K (最贵，无上限)
    op.execute(text(f"""
        INSERT INTO vendor_model
            (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        VALUES
            (1, {qwen35_model_id}, 10000, 1667, 100000, NULL)
    """))

    # === qwen3.6-plus 分段计费配置 ===

    # 档位1: 0~256K (便宜)
    op.execute(text(f"""
        INSERT INTO vendor_model
            (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        VALUES
            (1, {qwen36_model_id}, 20000, 3334, 200000, 256000)
    """))

    # 档位2: >256K (贵，无上限)
    op.execute(text(f"""
        INSERT INTO vendor_model
            (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        VALUES
            (1, {qwen36_model_id}, 5000, 834, 50000, NULL)
    """))


def downgrade() -> None:
    conn = op.get_bind()

    # 获取 model_id
    result = conn.execute(text("SELECT id FROM model WHERE model_name = 'qwen3.5-plus'"))
    row = result.fetchone()
    qwen35_model_id = row[0] if row else None

    result = conn.execute(text("SELECT id FROM model WHERE model_name = 'qwen3.6-plus'"))
    row = result.fetchone()
    qwen36_model_id = row[0] if row else None

    if qwen35_model_id and qwen36_model_id:
        # 删除分段计费配置
        op.execute(text(f"""
            DELETE FROM vendor_model 
            WHERE vendor_id = 1 AND model_id IN ({qwen35_model_id}, {qwen36_model_id})
        """))

        # 恢复原始单一计费配置
        op.execute(text(f"""
            INSERT INTO vendor_model 
                (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold)
            VALUES 
                (1, {qwen35_model_id}, 11000, 1800, 112000),
                (1, {qwen36_model_id}, 11000, 1800, 112000)
        """))
