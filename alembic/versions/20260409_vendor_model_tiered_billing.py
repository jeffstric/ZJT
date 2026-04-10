"""vendor_model 支持分段计费

1. 添加 raw_token_threshold 字段（分段边界）
2. 修改字段注释，澄清计费率含义
3. 移除 (vendor_id, model_id) 唯一约束
4. 为 gemini-3.1-pro-preview 配置两档计费

Revision ID: 20260409_tiered_billing
Revises: 20260409_create_unc_power
Create Date: 2026-04-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260409_tiered_billing'
down_revision: Union[str, None] = '20260409_create_unc_power'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # 1. 添加 raw_token_threshold 字段
    op.add_column('vendor_model', sa.Column(
        'raw_token_threshold',
        sa.Integer(),
        nullable=True,
        comment='分段边界：当raw_input_token<=此值时使用本档计费率，NULL表示无上限'
    ))

    # 2. 修改字段注释，澄清是计费率
    op.alter_column('vendor_model', 'input_token_threshold',
                    existing_type=sa.Integer(),
                    comment='输入token计费率：多少个input_token消耗1点算力')
    op.alter_column('vendor_model', 'out_token_threshold',
                    existing_type=sa.Integer(),
                    comment='输出token计费率：多少个output_token消耗1点算力')
    op.alter_column('vendor_model', 'cache_read_threshold',
                    existing_type=sa.Integer(),
                    comment='缓存读取计费率：多少个cache_read消耗1点算力')

    # 3. 移除 (vendor_id, model_id) 唯一约束
    indexes = inspector.get_indexes('vendor_model')
    unique_constraints = inspector.get_unique_constraints('vendor_model')

    for idx in indexes:
        if idx.get('unique') and set(idx.get('column_names', [])) == {'vendor_id', 'model_id'}:
            op.drop_index(idx['name'], table_name='vendor_model')

    for uc in unique_constraints:
        if set(uc.get('column_names', [])) == {'vendor_id', 'model_id'}:
            op.drop_constraint(uc['name'], 'vendor_model', type_='unique')

    # 4. 更新现有 gemini-3.1-pro-preview (jiekou) 为高档
    op.execute("""
        UPDATE vendor_model vm
        JOIN vendor v ON vm.vendor_id = v.id
        JOIN model m ON vm.model_id = m.id
        SET vm.input_token_threshold = 1500,
            vm.out_token_threshold = 340,
            vm.cache_read_threshold = 15000,
            vm.raw_token_threshold = NULL
        WHERE v.vendor_name = 'jiekou' AND m.model_name = 'gemini-3.1-pro-preview'
    """)

    # 5. 插入 gemini-3.1-pro-preview 低档记录（≤204K tokens）
    op.execute("""
        INSERT INTO vendor_model
            (vendor_id, model_id, input_token_threshold, out_token_threshold, cache_read_threshold, raw_token_threshold)
        SELECT v.id, m.id, 3000, 510, 30000, 204800
        FROM vendor v, model m
        WHERE v.vendor_name = 'jiekou' AND m.model_name = 'gemini-3.1-pro-preview'
    """)


def downgrade() -> None:
    # 删除低档记录
    op.execute("""
        DELETE vm FROM vendor_model vm
        JOIN vendor v ON vm.vendor_id = v.id
        JOIN model m ON vm.model_id = m.id
        WHERE v.vendor_name = 'jiekou' AND m.model_name = 'gemini-3.1-pro-preview'
          AND vm.raw_token_threshold = 204800
    """)

    # 恢复原始阈值
    op.execute("""
        UPDATE vendor_model vm
        JOIN vendor v ON vm.vendor_id = v.id
        JOIN model m ON vm.model_id = m.id
        SET vm.input_token_threshold = 1500,
            vm.out_token_threshold = 340,
            vm.cache_read_threshold = 15000,
            vm.raw_token_threshold = NULL
        WHERE v.vendor_name = 'jiekou' AND m.model_name = 'gemini-3.1-pro-preview'
    """)

    # 恢复唯一约束
    op.create_index(
        'idx_vendor_model_unique',
        'vendor_model',
        ['vendor_id', 'model_id'],
        unique=True
    )

    # 恢复字段注释
    op.alter_column('vendor_model', 'input_token_threshold',
                    existing_type=sa.Integer(),
                    comment='输入token阈值')
    op.alter_column('vendor_model', 'out_token_threshold',
                    existing_type=sa.Integer(),
                    comment='输出token阈值')
    op.alter_column('vendor_model', 'cache_read_threshold',
                    existing_type=sa.Integer(),
                    comment='缓存读取阈值')

    # 删除 raw_token_threshold 字段
    op.drop_column('vendor_model', 'raw_token_threshold')
