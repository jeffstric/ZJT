"""Add Ollama initial data (vendor, model, vendor_model)

Revision ID: 20260417_ollama_data
Revises: 20260417_supports_tools
Create Date: 2026-04-17

"""
import logging
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260417_ollama_data'
down_revision: Union[str, None] = '20260417_supports_tools'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Insert Ollama vendor, model and vendor_model data"""
    conn = op.get_bind()

    # 1. 插入 vendor 表 (ollama)，不指定 id，由 AUTO_INCREMENT 分配
    conn.execute(text("""
        INSERT INTO vendor (vendor_name, created_at, note)
        VALUES ('ollama', NOW(), 'ollama 本地')
        ON DUPLICATE KEY UPDATE vendor_name = VALUES(vendor_name)
    """))
    logger.info("[Migration] Inserted Ollama vendor")

    # 2. 插入 model 表 (qwen3.6:35b-a3b)，不指定 id，由 AUTO_INCREMENT 分配
    conn.execute(text("""
        INSERT INTO model (model_name, context_window, supports_tools, created_at, note)
        VALUES ('qwen3.6:35b-a3b', 250000, 1, NOW(), '')
        ON DUPLICATE KEY UPDATE model_name = VALUES(model_name), context_window = VALUES(context_window)
    """))
    logger.info("[Migration] Inserted Ollama model (qwen3.6:35b-a3b)")

    # 3. 插入 vendor_model 表 (动态查询 vendor_id 和 model_id，避免硬编码)
    conn.execute(text("""
        INSERT INTO vendor_model (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold)
        SELECT v.id, m.id, 200000, 10000, 100000
        FROM vendor v, model m
        WHERE v.vendor_name = 'ollama' AND m.model_name = 'qwen3.6:35b-a3b'
        ON DUPLICATE KEY UPDATE input_token_threshold = VALUES(input_token_threshold)
    """))
    logger.info("[Migration] Inserted vendor_model relation for Ollama (dynamic query)")


def downgrade() -> None:
    """Remove Ollama vendor, model and vendor_model data"""
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联 (动态查询，避免硬编码)
    conn.execute(text("""
        DELETE FROM vendor_model
        WHERE vendor_id IN (SELECT id FROM vendor WHERE vendor_name = 'ollama')
          AND model_id IN (SELECT id FROM model WHERE model_name = 'qwen3.6:35b-a3b')
    """))
    logger.info("[Migration] Removed vendor_model relation for Ollama (dynamic query)")

    # 2. 删除 model
    conn.execute(text("""
        DELETE FROM model WHERE model_name = 'qwen3.6:35b-a3b'
    """))
    logger.info("[Migration] Removed Ollama model")

    # 3. 删除 vendor
    conn.execute(text("""
        DELETE FROM vendor WHERE vendor_name = 'ollama'
    """))
    logger.info("[Migration] Removed Ollama vendor")
