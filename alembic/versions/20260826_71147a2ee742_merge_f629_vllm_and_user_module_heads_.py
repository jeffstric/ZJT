"""merge_f629_vllm_and_user_module_heads: 合并 vLLM/Ollama 配置链与用户模块链双 head

Revision ID: 71147a2ee742
Revises: 20260821_merge_heads, 20260825_disable_gem3flash
Create Date: 2026-08-26 20:04:50.287904+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '71147a2ee742'
down_revision: Union[str, None] = ('20260821_merge_heads', '20260825_disable_gem3flash')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库"""
    pass


def downgrade() -> None:
    """回滚数据库"""
    pass
