"""Disable gemini-3-flash-preview and switch system default to deepseek-v4-flash

gemini-3-flash-preview 下线：
1. model 表 enabled=0，前端可用模型列表不再展示（get_available_models 按 enabled 过滤）；
   存量会话/显式指定该模型名的调用仍走 JIEKOU 路由，行为不受影响。
2. chat_sessions.model 列默认值同步切到 deepseek-v4-flash（代码侧默认值已同步替换，
   见 model/chat_sessions.py CREATE_TABLE_SQL）。

计费相关（vendor_model）不动：模型仅下线，不删除。

Revision ID: 20260825_disable_gem3flash
Revises: 20260825_vllm_qwen38
Create Date: 2026-08-25
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 ≤ 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260825_disable_gem3flash'
down_revision: Union[str, None] = '20260825_vllm_qwen38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """下线 gemini-3-flash-preview，chat_sessions 默认模型切 deepseek-v4-flash"""
    conn = op.get_bind()

    # 1. model 表下线（UPDATE 天然幂等，重跑无副作用）
    conn.execute(text("""
        UPDATE `model` SET enabled = 0 WHERE model_name = 'gemini-3-flash-preview'
    """))
    logger.info("[Migration] Disabled model gemini-3-flash-preview")

    # 2. chat_sessions.model 列默认值（新插入行不再落到已下线模型）
    conn.execute(text("""
        ALTER TABLE `chat_sessions` ALTER `model` SET DEFAULT 'deepseek-v4-flash'
    """))
    logger.info("[Migration] chat_sessions.model default switched to deepseek-v4-flash")


def downgrade() -> None:
    """恢复 gemini-3-flash-preview 上线及原默认值"""
    conn = op.get_bind()

    conn.execute(text("""
        ALTER TABLE `chat_sessions` ALTER `model` SET DEFAULT 'gemini-3-flash-preview'
    """))
    logger.info("[Migration] chat_sessions.model default reverted to gemini-3-flash-preview")

    conn.execute(text("""
        UPDATE `model` SET enabled = 1 WHERE model_name = 'gemini-3-flash-preview'
    """))
    logger.info("[Migration] Re-enabled model gemini-3-flash-preview")
