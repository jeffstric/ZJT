"""Fix Qwen models vendor_id (should be aliyun, not jiekou)

Qwen3.5-plus 和 Qwen3.6-plus 的分段计费配置被错误地写入到了 vendor_id=1 (jiekou)，
应该改为 vendor_id 对应的 aliyun 供应商。

Revision ID: 20260420_fix_qwen_vendor
Revises: 20260417_ollama_data
Create Date: 2026-04-20

"""
import logging
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260420_fix_qwen_vendor'
down_revision: Union[str, None] = '20260417_ollama_data'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Move Qwen models from vendor_id=1 (jiekou) to correct aliyun vendor_id"""
    conn = op.get_bind()

    # 1. 从 vendor_id=1 转移 qwen 的 vendor_model 到 aliyun vendor
    conn.execute(text("""
        INSERT INTO vendor_model
            (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT
            (SELECT id FROM vendor WHERE vendor_name = 'aliyun'),
            model_id,
            created_at,
            input_token_threshold,
            out_token_threshold,
            cache_read_threshold,
            raw_token_threshold
        FROM vendor_model
        WHERE vendor_id = 1 AND model_id IN (
            SELECT id FROM model WHERE model_name IN ('qwen3.5-plus', 'qwen3.6-plus')
        )
    """))
    logger.info("[Migration] Migrated Qwen vendor_model from vendor_id=1 to aliyun vendor")

    # 2. 删除原有的错误记录
    conn.execute(text("""
        DELETE FROM vendor_model
        WHERE vendor_id = 1 AND model_id IN (
            SELECT id FROM model WHERE model_name IN ('qwen3.5-plus', 'qwen3.6-plus')
        )
    """))
    logger.info("[Migration] Deleted Qwen vendor_model from vendor_id=1 (jiekou)")


def downgrade() -> None:
    """Revert: Move Qwen models back from aliyun vendor to vendor_id=1"""
    conn = op.get_bind()

    # 1. 从 aliyun vendor 转移 qwen 的 vendor_model 回到 vendor_id=1
    conn.execute(text("""
        INSERT INTO vendor_model
            (vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT
            1,
            model_id,
            created_at,
            input_token_threshold,
            out_token_threshold,
            cache_read_threshold,
            raw_token_threshold
        FROM vendor_model vm
        WHERE vm.vendor_id = (SELECT id FROM vendor WHERE vendor_name = 'aliyun')
          AND model_id IN (
            SELECT id FROM model WHERE model_name IN ('qwen3.5-plus', 'qwen3.6-plus')
        )
    """))
    logger.info("[Migration] Reverted Qwen vendor_model from aliyun to vendor_id=1")

    # 2. 删除 aliyun 中的记录
    conn.execute(text("""
        DELETE FROM vendor_model
        WHERE vendor_id = (SELECT id FROM vendor WHERE vendor_name = 'aliyun')
          AND model_id IN (
            SELECT id FROM model WHERE model_name IN ('qwen3.5-plus', 'qwen3.6-plus')
        )
    """))
    logger.info("[Migration] Deleted Qwen vendor_model from aliyun vendor")
