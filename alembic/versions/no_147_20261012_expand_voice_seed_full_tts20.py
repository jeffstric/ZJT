"""expand voice seed full tts20

Revision ID: 20261012_expand_voice_seed_full
Revises: 20261012_switch_voice_seed_to_tt
Create Date: 2026-10-12

音色库种子扩充为语音合成 2.0 官方全量清单（177 个 / 16 种语言，
来源官方音色列表文档，中文 + 多语言代表已实测合成验证通过）。
幂等插入（voice_type 业务键去重）。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

from config.volcengine_tts_constants import VOLCENGINE_TTS_VOICES

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261012_expand_voice_seed_full'
down_revision: Union[str, None] = '20261012_switch_voice_seed_to_tt'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inserted = 0
    for item in VOLCENGINE_TTS_VOICES:
        result = conn.execute(text("""
            INSERT INTO `voice`
              (user_id, provider, voice_type, name, description, gender, language, style, sort_order, is_active)
            SELECT 0, 'volcengine', :voice_type, :name, :description, :gender, :language, :style, :sort_order, 1
            FROM DUAL
            WHERE NOT EXISTS (
                SELECT 1 FROM `voice`
                WHERE provider = 'volcengine' AND voice_type = :voice_type AND user_id = 0
            )
        """), item)
        inserted += (result.rowcount or 0)
    logger.info("[Migration] 2.0 音色全量种子写入完成（清单 %d 条，新插入 %d 条）",
                len(VOLCENGINE_TTS_VOICES), inserted)


def downgrade() -> None:
    # 数据修复类迁移不回滚（仅新增预置音色行）
    pass
