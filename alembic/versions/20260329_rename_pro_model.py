"""
将 gemini-3-pro-preview 模型改名为 gemini-3.1-pro-preview

因为 jiekou 的 gemini-3-pro-preview 模型已下线，需要切换到 gemini-3.1-pro-preview

Revision ID: 20260329_rename_pro_model
Revises: 20260329_gemini_flash_lite
Create Date: 2026-03-29

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20260329_rename_pro_model'
down_revision = '20260329_gemini_flash_lite'
branch_labels = None
depends_on = None


def upgrade():
    # 将 gemini-3-pro-preview 改名为 gemini-3.1-pro-preview
    op.execute("""
        UPDATE `model`
        SET model_name = 'gemini-3.1-pro-preview'
        WHERE model_name = 'gemini-3-pro-preview'
    """)


def downgrade():
    op.execute("""
        UPDATE `model`
        SET model_name = 'gemini-3-pro-preview'
        WHERE model_name = 'gemini-3.1-pro-preview'
    """)
