"""add llm.qwen and runninghub.max_concurrent_slots default configs

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
    插入 llm.qwen 和 runninghub.max_concurrent_slots 的默认值配置
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

    # runninghub.max_concurrent_slots（如果不存在则插入）
    result = conn.execute(text("SELECT COUNT(*) FROM system_config WHERE config_key = 'runninghub.max_concurrent_slots'"))
    if result.scalar() == 0:
        op.execute(text("""
            INSERT INTO system_config (env, config_key, config_value, value_type, description, editable, is_sensitive)
            VALUES ('prod', 'runninghub.max_concurrent_slots', '3', 'int', 'RunningHub 最大并发槽位数量，该值根据runninghub账号的并发数决定，可以查看 https://www.runninghub.cn/vip-rights/2 查看并发数，注意，必须支持api调用的套餐才能使用 26年3月 基础版为1 专业版为3 专业Plus版为5 Max 为20', 1, 0)
        """))


def downgrade() -> None:
    """
    回滚时不删除配置，只删除我们新增的 llm.qwen 相关配置
    （runninghub.max_concurrent_slots 原本就存在，不删除）
    """
    # 删除 llm.qwen 相关配置
    op.execute(text("DELETE FROM system_config WHERE config_key LIKE 'llm.qwen.%'"))
