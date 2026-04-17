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

    # 1. 插入 vendor 表 (id=3, ollama)
    conn.execute(text("""
        INSERT INTO vendor (id, vendor_name, created_at, note)
        VALUES (3, 'ollama', NOW(), 'ollama 本地')
        ON DUPLICATE KEY UPDATE vendor_name = VALUES(vendor_name)
    """))
    logger.info("[Migration] Inserted Ollama vendor (id=3)")

    # 2. 插入 model 表 (id=1000, qwen3.6:35b-a3b)
    conn.execute(text("""
        INSERT INTO model (id, model_name, context_window, supports_tools, created_at, note)
        VALUES (1000, 'qwen3.6:35b-a3b', 250000, 1, NOW(), '')
        ON DUPLICATE KEY UPDATE model_name = VALUES(model_name), context_window = VALUES(context_window)
    """))
    logger.info("[Migration] Inserted Ollama model (id=1000, qwen3.6:35b-a3b)")

    # 3. 插入 vendor_model 表 (vendor_id=3, model_id=1000)
    conn.execute(text("""
        INSERT INTO vendor_model (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold)
        VALUES (3, 1000, 100000, 10000, 100000)
        ON DUPLICATE KEY UPDATE input_token_threshold = VALUES(input_token_threshold)
    """))
    logger.info("[Migration] Inserted vendor_model relation (vendor_id=3, model_id=1000)")


def downgrade() -> None:
    """Remove Ollama vendor, model and vendor_model data"""
    conn = op.get_bind()

    # 1. 删除 vendor_model 关联
    conn.execute(text("""
        DELETE FROM vendor_model WHERE vendor_id = 3 AND model_id = 1000
    """))
    logger.info("[Migration] Removed vendor_model relation (vendor_id=3, model_id=1000)")

    # 2. 删除 model
    conn.execute(text("""
        DELETE FROM model WHERE id = 1000
    """))
    logger.info("[Migration] Removed Ollama model (id=1000)")

    # 3. 删除 vendor
    conn.execute(text("""
        DELETE FROM vendor WHERE id = 3
    """))
    logger.info("[Migration] Removed Ollama vendor (id=3)")
