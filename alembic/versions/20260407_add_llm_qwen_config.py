"""add llm.qwen default configs

Revision ID: 20260407_llm_qwen_config
Revises: 20260407_qwen_models
Create Date: 2026-04-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '20260407_llm_qwen_config'
down_revision: Union[str, None] = '20260407_qwen_models'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    插入 llm.qwen 的默认值配置
    仅插入不存在的记录，已存在的不处理
    """
    # 获取当前数据库中的 system_config 表名（可能带前缀）
    # 检查 system_config 表是否存在
    conn = op.get_bind()

    # llm.qwen.api_key
    result = conn.execute(text("SELECT COUNT(*) FROM system_config WHERE config_key = 'llm.qwen.api_key'"))
    if result.scalar() == 0:
        op.execute(text("""
            INSERT INTO system_config (env, config_key, config_value, value_type, description, editable, is_sensitive)
            VALUES ('prod', 'llm.qwen.api_key', '', 'string', 'Qwen API Key（阿里通义千问）', 1, 1)
        """))

    # llm.qwen.base_url
    result = conn.execute(text("SELECT COUNT(*) FROM system_config WHERE config_key = 'llm.qwen.base_url'"))
    if result.scalar() == 0:
        op.execute(text("""
            INSERT INTO system_config (env, config_key, config_value, value_type, description, editable, is_sensitive)
            VALUES ('prod', 'llm.qwen.base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'string', 'Qwen API 基础URL', 1, 0)
        """))

    # llm.qwen.model
    result = conn.execute(text("SELECT COUNT(*) FROM system_config WHERE config_key = 'llm.qwen.model'"))
    if result.scalar() == 0:
        op.execute(text("""
            INSERT INTO system_config (env, config_key, config_value, value_type, description, editable, is_sensitive)
            VALUES ('prod', 'llm.qwen.model', 'qwen-plus', 'string', 'Qwen 默认模型名称', 1, 0)
        """))


def downgrade() -> None:
    """
    回滚时删除 llm.qwen 相关配置
    """
    # 删除 llm.qwen 相关配置
    op.execute(text("DELETE FROM system_config WHERE config_key LIKE 'llm.qwen.%'"))
