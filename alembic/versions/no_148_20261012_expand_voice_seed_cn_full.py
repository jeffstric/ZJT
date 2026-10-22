"""expand voice seed cn full

Revision ID: 20261012_expand_voice_seed_cn_fu
Revises: 20261012_expand_voice_seed_full
Create Date: 2026-10-12

音色库种子扩充为国内控制台 ListSpeakers 接口的 uranus 代际全量
（244 个 / 16 语言，其中中文 90 个——此前 byteplus 海外表仅有 23 个中文）：
1. 插入新增 uranus 音色（幂等，voice_type 业务键去重）
2. 下线 byteplus 特有的无代际短 ID 音色（13 个，无法在 seed-tts-2.0 稳定合成）
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

from config.volcengine_tts_constants import VOLCENGINE_TTS_VOICES

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261012_expand_voice_seed_cn_fu'
down_revision: Union[str, None] = '20261012_expand_voice_seed_full'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# byteplus 文档特有短 ID（国内接口无此音色，统一下线）
DEPRECATED_SHORT_IDS = [
    'en_female_authoritative', 'en_female_female_tutor_ms', 'en_female_pleasant',
    'en_male_adam', 'en_male_bill', 'en_male_cowboy', 'en_male_deep',
    'en_male_evil', 'en_male_excited', 'en_male_father', 'en_male_fernando',
    'en_male_michael', 'en_male_motivational',
]


def upgrade() -> None:
    conn = op.get_bind()

    # 1. 下线 byteplus 特有短 ID 音色
    for vt in DEPRECATED_SHORT_IDS:
        conn.execute(text("""
            UPDATE `voice` SET is_active = 0
            WHERE provider = 'volcengine' AND user_id = 0 AND voice_type = :vt
        """), {"vt": vt})
    logger.info("[Migration] byteplus 短 ID 音色已下线 %d 个", len(DEPRECATED_SHORT_IDS))

    # 2. 幂等插入 uranus 全量清单
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
    logger.info("[Migration] uranus 全量清单 %d 条，新插入 %d 条（中文 %d 个）",
                len(VOLCENGINE_TTS_VOICES), inserted,
                sum(1 for v in VOLCENGINE_TTS_VOICES if v['language'] == 'zh'))


def downgrade() -> None:
    # 数据修复类迁移不回滚（仅新增预置音色行 + 下线旧 ID）
    pass
