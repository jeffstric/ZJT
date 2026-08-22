"""Add Ollama qwen3.8:27b model

上下文窗口与推荐参数来源：
- https://huggingface.co/Qwen/Qwen3.8-27B
  原生上下文 262,144 tokens，可扩展至 1,000,000
  最终回复建议 max_output_tokens=131,072
  支持工具调用 / 思考模式 / 视觉理解
- https://ollama.com/library/qwen3.8:27b
  标签：vision / tools / thinking；Ollama 模型 ID 为 qwen3.8:27b
  内置采样（思考模式）：temperature=1.0, top_p=0.95, top_k=20,
  min_p=0, presence_penalty=0, repeat_penalty=1

计费阈值对齐既有 ollama 模型 qwen3.6:35b-a3b：
input=200000 / out=10000 / cache=100000

Revision ID: 20260822_ollama_qwen38
Revises: 20260819_txn_idx
Create Date: 2026-08-22
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260822_ollama_qwen38'
down_revision: Union[str, None] = '20260819_txn_idx'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add qwen3.8:27b model and ollama vendor_model billing"""
    conn = op.get_bind()

    conn.execute(text("""
        INSERT INTO `model` (
            model_name, context_window, supports_tools, max_output_tokens,
            supports_thinking, supports_vl, created_at, note
        )
        SELECT 'qwen3.8:27b', 262144, 1, 131072, 1, 1, NOW(),
               'Ollama Qwen3.8-27B：原生 256K 上下文，支持工具/思考/视觉'
        WHERE NOT EXISTS (SELECT 1 FROM `model` WHERE model_name = 'qwen3.8:27b')
    """))
    logger.info("[Migration] Inserted Ollama model qwen3.8:27b")

    conn.execute(text("""
        INSERT INTO `vendor_model` (
            vendor_id, model_id, created_at,
            input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold
        )
        SELECT v.id, m.id, NOW(), 200000, 10000, 100000, NULL
        FROM `vendor` v, `model` m
        WHERE v.vendor_name = 'ollama' AND m.model_name = 'qwen3.8:27b'
        AND NOT EXISTS (
            SELECT 1 FROM vendor_model vm
            WHERE vm.vendor_id = v.id AND vm.model_id = m.id
        )
    """))
    logger.info(
        "[Migration] Added qwen3.8:27b billing under ollama: "
        "input=200000, out=10000, cache=100000"
    )

    # Qwen3.8 官方默认思考模式：把 Ollama 全局思维链打开
    conn.execute(text("""
        UPDATE system_config
        SET config_value = 'true'
        WHERE config_key = 'llm.ollama.enable_thinking'
          AND LOWER(config_value) IN ('false', '0', 'no')
    """))
    logger.info("[Migration] Enabled llm.ollama.enable_thinking for Qwen3.8 default thinking")


def downgrade() -> None:
    """Revert: Remove qwen3.8:27b vendor_model and model"""
    conn = op.get_bind()

    conn.execute(text("""
        DELETE FROM `vendor_model`
        WHERE vendor_id = (SELECT id FROM vendor WHERE vendor_name = 'ollama')
        AND model_id IN (SELECT id FROM `model` WHERE model_name = 'qwen3.8:27b')
    """))
    logger.info("[Migration] Deleted vendor_model records for qwen3.8:27b under ollama")

    conn.execute(text("""
        DELETE FROM `model` WHERE model_name = 'qwen3.8:27b'
    """))
    logger.info("[Migration] Deleted qwen3.8:27b model")

    conn.execute(text("""
        UPDATE system_config
        SET config_value = 'false'
        WHERE config_key = 'llm.ollama.enable_thinking'
          AND LOWER(config_value) IN ('true', '1', 'yes')
    """))
    logger.info("[Migration] Restored llm.ollama.enable_thinking to false")
