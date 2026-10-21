"""fix preset voice type null

no_152 种子曾把预置音色 voice_type 写成字符串 'NULL'。
已升级过的库在此改回 SQL NULL。未写入该字符串的行不受影响。

Revision ID: 20261016_fix_preset_voice_type_n
Revises: 20261016_voice_vdesc_seed
Create Date: 2026-10-16
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261016_fix_preset_voice_type_n'
down_revision: Union[str, None] = '20261016_voice_vdesc_seed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """把 reference_audio 上误写成字符串 NULL 的 voice_type 改回 SQL NULL。"""
    conn = op.get_bind()
    result = conn.execute(text(
        "UPDATE `voice` SET voice_type = NULL "
        "WHERE provider = 'reference_audio' AND voice_type = 'NULL'"
    ))
    logger.info("[Migration] cleared literal NULL voice_type rows=%s", result.rowcount)


def downgrade() -> None:
    """不把 SQL NULL 写回字符串 'NULL'，否则会重新引入误判。"""
    pass
