"""Add vLLM vendor and qwen3.8:27b (vLLM 驱动)

模型 qwen3.8:27b 已由 20260822_ollama_qwen38 插入 model 表（Ollama 供应商），
vLLM 供应商复用同一 model 记录（vendor_model 多对多关联），按 vendor_id 区分：
前端模型 ID 分别为 ollama:qwen3.8:27b / vllm:qwen3.8:27b。

计费阈值对齐既有 ollama qwen3.8:27b：
input=200000 / out=10000 / cache=100000（1 点算力 = 0.04 元）

Revision ID: 20260825_vllm_qwen38
Revises: 20260822_ollama_qwen38
Create Date: 2026-08-25
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260825_vllm_qwen38'
down_revision: Union[str, None] = '20260822_ollama_qwen38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add vllm vendor and vendor_model billing for qwen3.8:27b"""
    conn = op.get_bind()

    # 1. 插入 vendor 表 (vllm)，不指定 id，由 AUTO_INCREMENT 分配
    # 注意：vendor.vendor_name 无唯一约束，ON DUPLICATE KEY 不生效（重跑会重复插入），
    # 必须用 WHERE NOT EXISTS 保证幂等
    conn.execute(text("""
        INSERT INTO vendor (vendor_name, created_at, note)
        SELECT 'vllm', NOW(), 'vllm 本地推理'
        WHERE NOT EXISTS (SELECT 1 FROM vendor WHERE vendor_name = 'vllm')
    """))
    logger.info("[Migration] Inserted vllm vendor")

    # 2. 插入 vendor_model 关联（model qwen3.8:27b 已存在于 20260822 迁移，此处只建关联）
    # 阈值对齐既有 ollama qwen3.8:27b：input=200000 / out=10000 / cache=100000
    conn.execute(text("""
        INSERT INTO `vendor_model` (
            vendor_id, model_id, created_at,
            input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold
        )
        SELECT v.id, m.id, NOW(), 200000, 10000, 100000, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'vllm' AND m.model_name = 'qwen3.8:27b'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info(
        "[Migration] Added qwen3.8:27b billing under vllm: "
        "input=200000, out=10000, cache=100000"
    )


def downgrade() -> None:
    """Revert: Remove qwen3.8:27b vendor_model and vllm vendor"""
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联（只删 vllm 下的，不影响 ollama 同名模型）
    # 用 IN 而非 = ：vendor_name 无唯一约束，历史脏数据可能产生多行，标量子查询会报 1242
    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE vendor_id IN (SELECT id FROM vendor WHERE vendor_name = 'vllm')
        AND model_id IN (SELECT id FROM `model` WHERE model_name = 'qwen3.8:27b')
    """))
    logger.info("[Migration] Deleted vendor_model records for qwen3.8:27b under vllm")

    # 2. 删除 vllm 供应商（model qwen3.8:27b 仍被 ollama 使用，不能删）
    conn.execute(text("""
        DELETE FROM vendor WHERE vendor_name = 'vllm'
    """))
    logger.info("[Migration] Deleted vllm vendor")
