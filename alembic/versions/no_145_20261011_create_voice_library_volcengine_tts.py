"""create voice library volcengine tts

Revision ID: 20261011_create_voice_library_vo
Revises: 20261008_add_video_workflow_last
Create Date: 2026-10-11

内容：
1. 新建音色库表 voice（provider 维度：volcengine 预置 / reference_audio 预留）
2. 幂等插入火山免费预置音色种子（user_id=0，来源 config/volcengine_tts_constants.py）
3. ai_audio 增加 engine / voice_id 列（区分 IndexTTS 克隆与火山快速合成的历史记录）
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

import logging

from config.volcengine_tts_constants import VOLCENGINE_TTS_VOICES

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20261011_create_voice_library_vo'
down_revision: Union[str, None] = '20261008_add_video_workflow_last'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    count = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t
    """), {"t": table_name}).scalar()
    return bool(count)


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    count = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = :t AND COLUMN_NAME = :c
    """), {"t": table_name, "c": column_name}).scalar()
    return bool(count)


def upgrade() -> None:
    conn = op.get_bind()

    # 1. 建音色库表
    if not _table_exists(conn, 'voice'):
        conn.execute(text("""
            CREATE TABLE `voice` (
              `id` int NOT NULL AUTO_INCREMENT,
              `user_id` int NOT NULL DEFAULT 0 COMMENT '0=系统预置音色，>0=用户私有音色',
              `provider` varchar(32) NOT NULL DEFAULT 'volcengine' COMMENT '音色提供方: volcengine/reference_audio',
              `voice_type` varchar(128) DEFAULT NULL COMMENT '提供方音色ID，如 BV700_streaming',
              `name` varchar(128) NOT NULL COMMENT '显示名',
              `description` varchar(512) DEFAULT NULL COMMENT '一句话人设描述',
              `gender` varchar(16) DEFAULT NULL COMMENT 'female/male/child',
              `language` varchar(32) DEFAULT NULL COMMENT 'zh/zh-dialect/en 等',
              `style` varchar(64) DEFAULT NULL COMMENT '风格标签，如 温柔知性',
              `sample_url` varchar(512) DEFAULT NULL COMMENT '试听音频URL',
              `audio_url` varchar(512) DEFAULT NULL COMMENT '参考音频URL（reference_audio 克隆源）',
              `sort_order` int NOT NULL DEFAULT 0,
              `is_active` tinyint NOT NULL DEFAULT 1,
              `create_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
              `update_at` datetime DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (`id`),
              KEY `idx_provider` (`provider`),
              KEY `idx_user_id` (`user_id`),
              KEY `idx_voice_type` (`voice_type`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """))
        logger.info("[Migration] 建表 voice 完成")
    else:
        logger.info("[Migration] voice 表已存在，跳过建表")

    # 2. 幂等插入火山预置音色种子（voice_type 为业务键）
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
    logger.info("[Migration] 火山预置音色种子写入完成（共 %d 条清单，已存在自动跳过）", len(VOLCENGINE_TTS_VOICES))

    # 3. ai_audio 增加 engine / voice_id
    if not _column_exists(conn, 'ai_audio', 'engine'):
        conn.execute(text("""
            ALTER TABLE `ai_audio`
            ADD COLUMN `engine` varchar(16) DEFAULT NULL
            COMMENT '合成引擎: volcengine=火山快速合成; NULL=IndexTTS 克隆'
            AFTER `status`
        """))
        logger.info("[Migration] ai_audio 新增 engine 列")
    else:
        logger.info("[Migration] ai_audio.engine 已存在，跳过")

    if not _column_exists(conn, 'ai_audio', 'voice_id'):
        conn.execute(text("""
            ALTER TABLE `ai_audio`
            ADD COLUMN `voice_id` int DEFAULT NULL COMMENT 'voice 表关联ID（engine=volcengine 时记录）'
            AFTER `engine`
        """))
        logger.info("[Migration] ai_audio 新增 voice_id 列")
    else:
        logger.info("[Migration] ai_audio.voice_id 已存在，跳过")


def downgrade() -> None:
    conn = op.get_bind()
    # 只回滚结构，不删除音色数据（voice 表整体 drop 属于破坏性操作，需人工确认）
    if _column_exists(conn, 'ai_audio', 'voice_id'):
        conn.execute(text("ALTER TABLE `ai_audio` DROP COLUMN `voice_id`"))
    if _column_exists(conn, 'ai_audio', 'engine'):
        conn.execute(text("ALTER TABLE `ai_audio` DROP COLUMN `engine`"))
    logger.info("[Migration] 回滚 ai_audio engine/voice_id 列完成（voice 表与种子数据保留）")
