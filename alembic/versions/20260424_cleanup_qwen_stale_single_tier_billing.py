"""清理 qwen 模型在 aliyun vendor 下残留的单档计费记录

由于 20260409_qwen_tiered_billing 迁移中硬编码 vendor_id=1，
导致 aliyun 下的 qwen 单档计费记录未被删除（分段计费记录被错误插入到 vendor_id=1，
后由 20260420_fix_qwen_vendor_id 修正到 aliyun）。
最终 aliyun 下同时存在：旧的单档记录 + 新的分段计费记录。
本迁移清理这些残留的单档记录。

Revision ID: 20260424_cleanup_qwen_stale
Revises: 20260423_gpt_image_2_power
Create Date: 2026-04-24

"""
import logging
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = '20260424_cleanup_qwen_stale'
down_revision: Union[str, None] = '20260423_gpt_image_2_power'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除 aliyun vendor 下 qwen 模型残留的单档计费记录（raw_token_threshold IS NULL 的旧记录）"""
    conn = op.get_bind()

    # 查找并删除残留：aliyun vendor 下，qwen 模型，raw_token_threshold IS NULL 的单档记录
    # 分段计费记录中 raw_token_threshold=NULL 表示"无上限档位"，但单档记录的特征是：
    # 同一个 (vendor_id, model_id) 只有 1 条且 raw_token_threshold IS NULL
    # 而分段计费有多条记录，其中仅最后一条 raw_token_threshold IS NULL
    # 所以更安全的做法：删除 aliyun 下 qwen 模型中 input_token_threshold=11000, out_token_threshold=1800, cache_read_threshold=112000 的记录
    # 这是 20260407_add_qwen_models 插入的原始值，分段计费中没有这个组合
    result = conn.execute(text("""
        DELETE FROM vendor_model
        WHERE vendor_id = (SELECT id FROM vendor WHERE vendor_name = 'aliyun')
          AND model_id IN (SELECT id FROM model WHERE model_name IN ('qwen3.5-plus', 'qwen3.6-plus'))
          AND input_token_threshold = 11000
          AND out_token_threshold = 1800
          AND cache_read_threshold = 112000
          AND raw_token_threshold IS NULL
    """))
    deleted_count = result.rowcount
    logger.info(f"[Migration] Cleaned up {deleted_count} stale single-tier billing records for qwen models under aliyun vendor")


def downgrade() -> None:
    """恢复被删除的单档计费记录"""
    conn = op.get_bind()

    # 获取 aliyun vendor_id
    result = conn.execute(text("SELECT id FROM vendor WHERE vendor_name = 'aliyun'"))
    row = result.fetchone()
    if not row:
        logger.info("[Migration] aliyun vendor not found, skip downgrade")
        return
    aliyun_vendor_id = row[0]

    # 获取 model_id
    result = conn.execute(text("SELECT id FROM model WHERE model_name = 'qwen3.5-plus'"))
    row = result.fetchone()
    qwen35_model_id = row[0] if row else None

    result = conn.execute(text("SELECT id FROM model WHERE model_name = 'qwen3.6-plus'"))
    row = result.fetchone()
    qwen36_model_id = row[0] if row else None

    if not qwen35_model_id or not qwen36_model_id:
        logger.info("[Migration] qwen models not found, skip downgrade")
        return

    # 检查是否已存在单档记录，避免重复插入
    for model_id in [qwen35_model_id, qwen36_model_id]:
        check = conn.execute(text(f"""
            SELECT COUNT(*) FROM vendor_model
            WHERE vendor_id = {aliyun_vendor_id} AND model_id = {model_id}
              AND input_token_threshold = 11000
              AND out_token_threshold = 1800
              AND cache_read_threshold = 112000
              AND raw_token_threshold IS NULL
        """))
        if check.fetchone()[0] == 0:
            conn.execute(text(f"""
                INSERT INTO vendor_model
                    (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
                VALUES
                    ({aliyun_vendor_id}, {model_id}, 11000, 1800, 112000, NULL)
            """))
    logger.info("[Migration] Restored single-tier billing records for qwen models under aliyun vendor")
