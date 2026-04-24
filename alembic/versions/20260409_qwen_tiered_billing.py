"""qwen 模型配置分段计费

为 qwen3.5-plus 和 qwen3.6-plus 配置分段计费：
- qwen3.5-plus: 3个档位 (0-128K, 128K-256K, >256K)
- qwen3.6-plus: 2个档位 (0-256K, >256K)

Revision ID: 20260409_qwen_tiered
Revises: 20260407_llm_qwen_config
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '20260409_qwen_tiered'
down_revision: Union[str, None] = '20260407_llm_qwen_config'
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

    # 获取 aliyun vendor_id（替代硬编码 vendor_id = 1）
    result = conn.execute(text("SELECT id FROM vendor WHERE vendor_name = 'aliyun'"))
    row = result.fetchone()
    aliyun_vendor_id = row[0] if row else None

    if not aliyun_vendor_id:
        raise Exception("aliyun vendor 不存在，请先运行 20260407_add_qwen_models 迁移")

    # 删除现有的单一计费配置
    conn.execute(text(f"""
        DELETE FROM vendor_model
        WHERE vendor_id = {aliyun_vendor_id} AND model_id IN ({qwen35_model_id}, {qwen36_model_id})
    """))

    # === qwen3.5-plus 分段计费配置 ===

    # 档位1: 0~128K (最便宜)
    conn.execute(text(f"""
        INSERT INTO vendor_model
            (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        VALUES
            ({aliyun_vendor_id}, {qwen35_model_id}, 50000, 8334, 500000, 128000)
    """))

    # 档位2: 128K~256K (中档)
    conn.execute(text(f"""
        INSERT INTO vendor_model
            (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        VALUES
            ({aliyun_vendor_id}, {qwen35_model_id}, 20000, 3334, 200000, 256000)
    """))

    # 档位3: >256K (最贵，无上限)
    conn.execute(text(f"""
        INSERT INTO vendor_model
            (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        VALUES
            ({aliyun_vendor_id}, {qwen35_model_id}, 10000, 1667, 100000, NULL)
    """))

    # === qwen3.6-plus 分段计费配置 ===

    # 档位1: 0~256K (便宜)
    conn.execute(text(f"""
        INSERT INTO vendor_model
            (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        VALUES
            ({aliyun_vendor_id}, {qwen36_model_id}, 20000, 3334, 200000, 256000)
    """))

    # 档位2: >256K (贵，无上限)
    conn.execute(text(f"""
        INSERT INTO vendor_model
            (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        VALUES
            ({aliyun_vendor_id}, {qwen36_model_id}, 5000, 834, 50000, NULL)
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
        # 获取 aliyun vendor_id
        result = conn.execute(text("SELECT id FROM vendor WHERE vendor_name = 'aliyun'"))
        row = result.fetchone()
        aliyun_vendor_id = row[0] if row else None

        if aliyun_vendor_id:
            # 删除分段计费配置
            conn.execute(text(f"""
                DELETE FROM vendor_model
                WHERE vendor_id = {aliyun_vendor_id} AND model_id IN ({qwen35_model_id}, {qwen36_model_id})
            """))

            # 恢复原始单一计费配置
            conn.execute(text(f"""
                INSERT INTO vendor_model
                    (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold)
                VALUES
                    ({aliyun_vendor_id}, {qwen35_model_id}, 11000, 1800, 112000),
                    ({aliyun_vendor_id}, {qwen36_model_id}, 11000, 1800, 112000)
            """))
