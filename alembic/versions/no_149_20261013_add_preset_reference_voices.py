"""add preset reference voices

Revision ID: 20261013_add_preset_reference_vo
Revises: 20261012_expand_voice_seed_cn_fu
Create Date: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

from config.voice_presets import PRESET_REFERENCE_VOICES

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261013_add_preset_reference_vo'
down_revision: Union[str, None] = '20261012_expand_voice_seed_cn_fu'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inserted = 0
    for item in PRESET_REFERENCE_VOICES:
        result = conn.execute(text("""
            INSERT INTO `voice`
              (user_id, provider, voice_type, name, description, gender, language,
               style, sample_url, audio_url, sort_order, is_active)
            SELECT 0, :provider, NULL, :name, :description, :gender, :language,
                   :style, :audio_url, :audio_url, :sort_order, 1
            FROM DUAL
            WHERE NOT EXISTS (
                SELECT 1 FROM `voice`
                WHERE provider = :provider AND user_id = 0 AND audio_url = :audio_url
            )
        """), {
            "provider": item["provider"],
            "name": item["name"],
            "description": item["description"],
            "gender": item["gender"],
            "language": item["language"],
            "style": item["style"],
            "audio_url": item["audio_url"],
            "sort_order": item["sort_order"],
        })
        inserted += (result.rowcount or 0)
    logger.info("[Migration] 预置参考音色写入完成（清单 %d 条，新插入 %d 条）",
                len(PRESET_REFERENCE_VOICES), inserted)


def downgrade() -> None:
    pass
