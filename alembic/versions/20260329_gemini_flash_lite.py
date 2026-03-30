"""
添加 gemini-3.1-flash-lite-preview 模型

用于剧本智能创作系统的新模型选项，价格为 gemini-3-flash-preview 的一半
对应 thresholds 为 gemini-3-flash-preview 的 2 倍

Revision ID: 20260329_gemini_flash_lite
Revises: 20260326_add_stats_index
Create Date: 2026-03-29

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260329_gemini_flash_lite'
down_revision = '20260326_add_stats_index'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 添加 gemini-3.1-flash-lite-preview 模型到 model 表
    op.execute("""
        INSERT INTO `model` (id, model_name, created_at, note)
        VALUES (3, 'gemini-3.1-flash-lite-preview', NOW(), NULL)
    """)

    # 2. 添加计费阈值配置到 vendor_model 表
    # gemini-3-flash-preview 的 thresholds: 11000, 1800, 112000
    # gemini-3.1-flash-lite-preview 价格是其一半，所以 thresholds 翻倍
    op.execute("""
        INSERT INTO `vendor_model` (id, vendor_id, model_id, created_at, input_token_threshold, out_token_threshold, cache_read_threshold)
        VALUES (3, 1, 3, NOW(), 22000, 3600, 224000)
    """)


def downgrade():
    op.execute("DELETE FROM `vendor_model` WHERE model_id = 3")
    op.execute("DELETE FROM `model` WHERE id = 3")
