"""switch voice seed to tts20

Revision ID: 20261012_switch_voice_seed_to_tt
Revises: 20261011_create_voice_library_vo
Create Date: 2026-10-12

音色库种子从旧版大模型 TTS（BV*_streaming）切换到语音合成 2.0
（*_uranus_bigtts，resource_id=seed-tts-2.0，2026-10-12 逐一合成验证通过）：
1. 旧 BV 音色 is_active=0（保留历史记录关联，不删除）
2. 幂等插入 2.0 音色种子（来源 config/volcengine_tts_constants.py）
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

from config.volcengine_tts_constants import VOLCENGINE_TTS_VOICES

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261012_switch_voice_seed_to_tt'
down_revision: Union[str, None] = '20261011_create_voice_library_vo'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. 旧版 BV 音色下线（2.0 资源不兼容 BV*_streaming，实测 speaker mismatch）
    result = conn.execute(text("""
        UPDATE `voice` SET is_active = 0
        WHERE provider = 'volcengine' AND user_id = 0
          AND voice_type LIKE 'BV%'
          AND voice_type NOT LIKE '%uranus%'
    """))
    logger.info("[Migration] 旧版 BV 音色已下线 %d 条", result.rowcount or 0)

    # 2. 幂等插入 2.0 音色种子
    for item in VOLCENGINE_TTS_VOICES:
        conn.execute(text("""
            INSERT INTO `voice`
              (user_id, provider, voice_type, name, description, gender, language, style, sort_order, is_active)
            SELECT 0, 'volcengine', :voice_type, :name, :description, :gender, :language, :style, :sort_order, 1
            FROM DUAL
            WHERE NOT EXISTS (
                SELECT 1 FROM `voice`
                WHERE provider = 'volcengine' AND voice_type = :voice_type AND user_id = 0
            )
        """), item)
    logger.info("[Migration] 语音合成 2.0 音色种子写入完成（共 %d 条清单）", len(VOLCENGINE_TTS_VOICES))


def downgrade() -> None:
    # 数据修复类迁移不回滚（旧音色仅置 is_active=0，无结构变更）
    pass
