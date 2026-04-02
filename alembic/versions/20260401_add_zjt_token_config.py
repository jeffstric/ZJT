"""add_zjt_token_config

Revision ID: 20260401_add_zjt_token_config
Revises: 20260401_add_api_token_to_users
Create Date: 2026-04-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260401_add_zjt_token_config'
down_revision: Union[str, None] = '20260401_add_api_token_to_users'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加智剧通(zjt.token)配置到 system_config 表"""
    # 为所有环境添加 zjt.token 配置
    op.execute("""
        INSERT INTO `system_config` (`env`, `config_key`, `config_value`, `value_type`, `description`, `editable`, `is_sensitive`)
        SELECT 'dev', 'zjt.token', '', 'string', '智剧通 API Token', 1, 1
        WHERE NOT EXISTS (SELECT 1 FROM `system_config` WHERE `env` = 'dev' AND `config_key` = 'zjt.token')
        UNION ALL
        SELECT 'prod', 'zjt.token', '', 'string', '智剧通 API Token', 1, 1
        WHERE NOT EXISTS (SELECT 1 FROM `system_config` WHERE `env` = 'prod' AND `config_key` = 'zjt.token')
        UNION ALL
        SELECT 'test', 'zjt.token', '', 'string', '智剧通 API Token', 1, 1
        WHERE NOT EXISTS (SELECT 1 FROM `system_config` WHERE `env` = 'test' AND `config_key` = 'zjt.token')
    """)


def downgrade() -> None:
    """删除智剧通(zjt.token)配置"""
    op.execute("DELETE FROM `system_config` WHERE `config_key` = 'zjt.token'")
