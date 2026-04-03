"""merge multi_ref and api_token_idx

Revision ID: 11d9d3eb5f7b
Revises: 20260401_add_api_token_idx, 20260402_multi_ref
Create Date: 2026-04-02 19:30:12.750725+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11d9d3eb5f7b'
down_revision: Union[str, None] = ('20260401_add_api_token_idx', '20260402_multi_ref')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级数据库"""
    pass


def downgrade() -> None:
    """回滚数据库"""
    pass
