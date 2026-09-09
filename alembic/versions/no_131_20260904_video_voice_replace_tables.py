"""video voice replace tables

Revision ID: 20260904_video_voice_replace_tab
Revises: 20260908_add_video_workflow_cont
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op

import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
# ⚠️ revision 长度必须 <= 32 字符 (alembic_version.version_num 为 varchar(32))
revision: str = '20260904_video_voice_replace_tab'
down_revision: Union[str, None] = '20260908_add_video_workflow_cont'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建成片对白音色替换任务表。"""
    op.execute("""
        CREATE TABLE IF NOT EXISTS `video_voice_replace_job` (
            `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            `user_id` INT UNSIGNED NOT NULL,
            `source_type` VARCHAR(32) NOT NULL COMMENT 'storyboard_scene | workflow_node',
            `scene_id` INT UNSIGNED DEFAULT NULL,
            `workflow_id` VARCHAR(64) DEFAULT NULL,
            `node_id` VARCHAR(64) DEFAULT NULL,
            `source_video_url` VARCHAR(1024) DEFAULT NULL,
            `result_video_url` VARCHAR(1024) DEFAULT NULL,
            `status` VARCHAR(32) NOT NULL DEFAULT 'queued',
            `match_json` JSON DEFAULT NULL,
            `skip_reason` VARCHAR(64) DEFAULT NULL,
            `error_message` VARCHAR(512) DEFAULT NULL,
            `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX `idx_user_status` (`user_id`, `status`),
            INDEX `idx_scene` (`scene_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='成片对白音色替换任务'
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS `video_voice_replace_segment` (
            `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            `job_id` INT UNSIGNED NOT NULL,
            `start_ms` INT NOT NULL DEFAULT 0,
            `end_ms` INT NOT NULL DEFAULT 0,
            `speaker_id` VARCHAR(32) DEFAULT NULL,
            `asr_text` TEXT DEFAULT NULL,
            `dialogue_id` INT UNSIGNED DEFAULT NULL,
            `character_id` INT UNSIGNED DEFAULT NULL,
            `match_method` VARCHAR(32) DEFAULT NULL,
            `match_confidence` DECIMAL(6,4) DEFAULT NULL,
            `source_clip_url` VARCHAR(1024) DEFAULT NULL,
            `converted_clip_url` VARCHAR(1024) DEFAULT NULL,
            `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX `idx_job` (`job_id`, `start_ms`),
            CONSTRAINT `fk_voice_replace_seg_job` FOREIGN KEY (`job_id`)
                REFERENCES `video_voice_replace_job` (`id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='成片对白音色替换切段'
    """)
    logger.info("created video_voice_replace_job / video_voice_replace_segment")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `video_voice_replace_segment`")
    op.execute("DROP TABLE IF EXISTS `video_voice_replace_job`")
