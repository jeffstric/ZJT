"""rename_google_config_keys

将 google.* 配置 key 重命名为 llm.google.*

Revision ID: 20260302_google_llm
Revises: 20260228_sysconfig
Create Date: 2026-03-02 14:35:00.000000+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260302_google_llm'
down_revision: Union[str, None] = '20260228_sysconfig'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库：将 google.* 配置 key 重命名为 llm.google.*"""
    
    # 重命名 system_config 表中的配置 key
    op.execute("""
        UPDATE `system_config` 
        SET `config_key` = 'llm.google.api_key' 
        WHERE `config_key` = 'google.api_key'
    """)
    
    op.execute("""
        UPDATE `system_config` 
        SET `config_key` = 'llm.google.gemini_base_url' 
        WHERE `config_key` = 'google.gemini_base_url'
    """)
    
    # 同步更新 system_config_history 表中的历史记录
    op.execute("""
        UPDATE `system_config_history` 
        SET `config_key` = 'llm.google.api_key' 
        WHERE `config_key` = 'google.api_key'
    """)
    
    op.execute("""
        UPDATE `system_config_history` 
        SET `config_key` = 'llm.google.gemini_base_url' 
        WHERE `config_key` = 'google.gemini_base_url'
    """)


def downgrade() -> None:
    """回滚数据库：将 llm.google.* 配置 key 恢复为 google.*"""
    
    # 恢复 system_config 表中的配置 key
    op.execute("""
        UPDATE `system_config` 
        SET `config_key` = 'google.api_key' 
        WHERE `config_key` = 'llm.google.api_key'
    """)
    
    op.execute("""
        UPDATE `system_config` 
        SET `config_key` = 'google.gemini_base_url' 
        WHERE `config_key` = 'llm.google.gemini_base_url'
    """)
    
    # 同步恢复 system_config_history 表中的历史记录
    op.execute("""
        UPDATE `system_config_history` 
        SET `config_key` = 'google.api_key' 
        WHERE `config_key` = 'llm.google.api_key'
    """)
    
    op.execute("""
        UPDATE `system_config_history` 
        SET `config_key` = 'google.gemini_base_url' 
        WHERE `config_key` = 'llm.google.gemini_base_url'
    """)
