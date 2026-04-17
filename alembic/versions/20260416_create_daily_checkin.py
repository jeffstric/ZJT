"""创建 daily_checkin 表用于每日签到功能

1. 创建 daily_checkin 表（签到记录）
2. 插入签到相关默认配置到 system_config

Revision ID: 20260416_daily_checkin
Revises: 20260409_qwen_tiered
Create Date: 2026-04-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260416_daily_checkin'
down_revision: Union[str, None] = '20260416_fix_driver_key_case'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 创建 daily_checkin 表
    op.create_table(
        'daily_checkin',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='用户ID'),
        sa.Column('checkin_date', sa.Date(), nullable=False, comment='签到日期'),
        sa.Column('streak_days', sa.Integer(), server_default='1', nullable=False, comment='连续签到天数'),
        sa.Column('base_reward', sa.Integer(), server_default='0', nullable=False, comment='基础奖励算力'),
        sa.Column('bonus_reward', sa.Integer(), server_default='0', nullable=False, comment='连续签到额外奖励算力'),
        sa.Column('reward_amount', sa.Integer(), server_default='0', nullable=False, comment='总奖励算力(基础+额外)'),
        sa.Column('transaction_id', sa.String(100), nullable=True, comment='幂等交易ID'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), comment='签到时间'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'checkin_date', name='uk_user_date'),
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_0900_ai_ci',
        comment='每日签到记录表'
    )
    op.create_index('idx_user_created', 'daily_checkin', ['user_id', 'created_at'])

    # 2. 插入默认签到配置到 system_config
    conn = op.get_bind()
    import os
    env = os.getenv('comfyui_env', 'dev')

    configs = [
        ('checkin.enabled', 'false', '是否启用每日签到功能', 'bool'),
        ('checkin.base_reward', '10', '每日签到基础奖励算力值', 'int'),
        ('checkin.streak_bonus_enabled', 'true', '是否启用连续签到额外奖励', 'bool'),
        ('checkin.streak_bonus_config', '{"3": 6, "7": 15, "14": 40, "30": 80}', '连续签到奖励配置', 'json'),
    ]

    for key, value, description, value_type in configs:
        conn.execute(sa.text("""
            INSERT INTO system_config (env, config_key, config_value, description, value_type, created_at, updated_at)
            VALUES (:env, :key, :value, :desc, :vtype, NOW(), NOW())
            ON DUPLICATE KEY UPDATE updated_at = NOW()
        """), {
            'env': env,
            'key': key,
            'value': value,
            'desc': description,
            'vtype': value_type,
        })


def downgrade() -> None:
    op.drop_index('idx_user_created', 'daily_checkin')
    op.drop_table('daily_checkin')

    # 删除签到配置
    conn = op.get_bind()
    import os
    env = os.getenv('comfyui_env', 'dev')
    conn.execute(sa.text("""
        DELETE FROM system_config WHERE env = :env AND config_key LIKE 'checkin.%'
    """), {'env': env})
