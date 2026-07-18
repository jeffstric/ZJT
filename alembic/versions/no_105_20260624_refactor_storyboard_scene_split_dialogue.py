"""Refactor storyboard_scene: split dialogue, asset linkage, video_type

重构 storyboard_scene：
- 删除音频/图片/视频单值字段，拆出 storyboard_dialogue（对话表）、
  storyboard_dialogue_audio（配音历史）、storyboard_scene_asset（图片/视频资产）
- scene 新增 video_prompt / video_type / selected_*_id / last_modified_user_id
- sort_order 改为 DOUBLE（浮点二分排序）

Revision ID: 20260624_storyboard_v2
Revises: 20260624_storyboard_comp
Create Date: 2026-06-24
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '20260624_storyboard_v2'
down_revision: Union[str, None] = '20260624_storyboard_comp'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """重构 storyboard_scene + 新建 dialogue / dialogue_audio / scene_asset"""

    # 1. storyboard_scene: sort_order 改 DOUBLE + 新增列
    op.execute("""
        ALTER TABLE `storyboard_scene`
          MODIFY COLUMN `sort_order` DOUBLE DEFAULT 0 COMMENT '排序序号（浮点二分，见文档 2.3.2）',
          ADD COLUMN `video_prompt` TEXT DEFAULT NULL COMMENT '视频提示词（生视频/数字人动作描述）' AFTER `prompt_json`,
          ADD COLUMN `video_type` VARCHAR(32) NOT NULL DEFAULT 'video' COMMENT '分镜类型 image/video/digital_human，见 SceneVideoType' AFTER `video_prompt`,
          ADD COLUMN `selected_first_frame_id` INT UNSIGNED DEFAULT NULL COMMENT '当前选中首帧 asset id' AFTER `video_config_json`,
          ADD COLUMN `selected_last_frame_id` INT UNSIGNED DEFAULT NULL COMMENT '当前选中尾帧 asset id' AFTER `selected_first_frame_id`,
          ADD COLUMN `selected_video_id` INT UNSIGNED DEFAULT NULL COMMENT '当前选中视频 asset id' AFTER `selected_last_frame_id`,
          ADD COLUMN `last_modified_user_id` INT UNSIGNED DEFAULT NULL COMMENT '最后修改人' AFTER `selected_video_id`
    """)

    # 2. storyboard_scene: 索引调整
    op.execute("""
        ALTER TABLE `storyboard_scene`
          DROP INDEX `idx_image_task`,
          DROP INDEX `idx_video_task`,
          DROP INDEX `idx_voice_task`,
          ADD INDEX `idx_video_type` (`video_type`),
          ADD INDEX `idx_selected_video` (`selected_video_id`)
    """)

    # 3. storyboard_scene: 删除音频/图片/视频单值字段
    op.execute("""
        ALTER TABLE `storyboard_scene`
          DROP COLUMN `thumbnail_url`,
          DROP COLUMN `preview_image_url`,
          DROP COLUMN `voiceover_text`,
          DROP COLUMN `voiceover_audio_url`,
          DROP COLUMN `voice_config_json`,
          DROP COLUMN `music_json`,
          DROP COLUMN `first_frame_url`,
          DROP COLUMN `last_frame_url`,
          DROP COLUMN `video_url`,
          DROP COLUMN `image_task_id`,
          DROP COLUMN `image_status`,
          DROP COLUMN `image_error`,
          DROP COLUMN `video_task_id`,
          DROP COLUMN `video_status`,
          DROP COLUMN `video_error`,
          DROP COLUMN `voice_task_id`,
          DROP COLUMN `voice_status`,
          DROP COLUMN `voice_error`
    """)

    # 4. 新建 storyboard_dialogue（分镜对话表）
    op.execute("""
        CREATE TABLE IF NOT EXISTS `storyboard_dialogue` (
            `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            `scene_id` INT UNSIGNED NOT NULL,
            `sort_order` DOUBLE DEFAULT 0 COMMENT '对话顺序（浮点二分，同 storyboard_scene）',
            `character_id` INT UNSIGNED DEFAULT NULL COMMENT '说话角色; NULL=旁白',
            `text` TEXT DEFAULT NULL COMMENT '台词',
            `speed` DECIMAL(4,2) NOT NULL DEFAULT 1.00 COMMENT '语速',
            `volume` INT NOT NULL DEFAULT 100 COMMENT '音量 0-100',
            `selected_audio_id` INT UNSIGNED DEFAULT NULL COMMENT '当前选中配音 → storyboard_dialogue_audio.id',
            `last_modified_user_id` INT UNSIGNED DEFAULT NULL COMMENT '最后修改人',
            `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX `idx_scene` (`scene_id`, `sort_order`),
            INDEX `idx_character` (`character_id`),
            FOREIGN KEY (`scene_id`) REFERENCES `storyboard_scene`(`id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分镜对话表'
    """)

    # 5. 新建 storyboard_dialogue_audio（配音生成历史）
    op.execute("""
        CREATE TABLE IF NOT EXISTS `storyboard_dialogue_audio` (
            `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            `dialogue_id` INT UNSIGNED NOT NULL,
            `ai_audio_id` INT DEFAULT NULL COMMENT '→ ai_audio.id（源表 int，不加外键）',
            `audio_url` VARCHAR(512) DEFAULT NULL COMMENT '配音结果 URL（冗余）',
            `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX `idx_dialogue` (`dialogue_id`),
            INDEX `idx_ai_audio` (`ai_audio_id`),
            FOREIGN KEY (`dialogue_id`) REFERENCES `storyboard_dialogue`(`id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分镜对话配音历史表'
    """)

    # 6. 新建 storyboard_scene_asset（图片/视频资产）
    op.execute("""
        CREATE TABLE IF NOT EXISTS `storyboard_scene_asset` (
            `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            `scene_id` INT UNSIGNED NOT NULL,
            `ai_tool_id` INT DEFAULT NULL COMMENT '→ ai_tools.id（源表 int，不加外键）',
            `asset_type` VARCHAR(32) NOT NULL COMMENT 'first_frame / last_frame / video',
            `result_url` VARCHAR(512) DEFAULT NULL COMMENT '结果 URL（图片或视频，冗余）',
            `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX `idx_scene` (`scene_id`, `asset_type`),
            INDEX `idx_ai_tool` (`ai_tool_id`),
            FOREIGN KEY (`scene_id`) REFERENCES `storyboard_scene`(`id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分镜图片/视频资产表'
    """)


def downgrade() -> None:
    """回滚：删 3 新表，恢复 storyboard_scene 旧结构"""

    # 1. 删除新表（asset → dialogue_audio → dialogue，按 FK 依赖逆序）
    op.execute("DROP TABLE IF EXISTS `storyboard_scene_asset`")
    op.execute("DROP TABLE IF EXISTS `storyboard_dialogue_audio`")
    op.execute("DROP TABLE IF EXISTS `storyboard_dialogue`")

    # 2. storyboard_scene: 恢复旧索引
    op.execute("""
        ALTER TABLE `storyboard_scene`
          DROP INDEX `idx_video_type`,
          DROP INDEX `idx_selected_video`,
          ADD INDEX `idx_image_task` (`image_task_id`),
          ADD INDEX `idx_video_task` (`video_task_id`),
          ADD INDEX `idx_voice_task` (`voice_task_id`)
    """)

    # 3. storyboard_scene: 恢复旧字段
    op.execute("""
        ALTER TABLE `storyboard_scene`
          ADD COLUMN `thumbnail_url` VARCHAR(512) DEFAULT NULL,
          ADD COLUMN `preview_image_url` VARCHAR(512) DEFAULT NULL,
          ADD COLUMN `voiceover_text` TEXT DEFAULT NULL COMMENT '配音台词',
          ADD COLUMN `voiceover_audio_url` VARCHAR(512) DEFAULT NULL,
          ADD COLUMN `voice_config_json` JSON DEFAULT NULL COMMENT '语速/音量/音色',
          ADD COLUMN `music_json` JSON DEFAULT NULL COMMENT '背景音乐配置',
          ADD COLUMN `first_frame_url` VARCHAR(512) DEFAULT NULL COMMENT '首帧图片',
          ADD COLUMN `last_frame_url` VARCHAR(512) DEFAULT NULL COMMENT '尾帧图片',
          ADD COLUMN `video_url` VARCHAR(512) DEFAULT NULL COMMENT '生成的视频',
          ADD COLUMN `image_task_id` VARCHAR(128) DEFAULT NULL,
          ADD COLUMN `image_status` TINYINT DEFAULT 0 COMMENT '0=未开始 1=生成中 2=成功 3=失败',
          ADD COLUMN `image_error` VARCHAR(512) DEFAULT NULL,
          ADD COLUMN `video_task_id` VARCHAR(128) DEFAULT NULL,
          ADD COLUMN `video_status` TINYINT DEFAULT 0 COMMENT '0=未开始 1=生成中 2=成功 3=失败',
          ADD COLUMN `video_error` VARCHAR(512) DEFAULT NULL,
          ADD COLUMN `voice_task_id` VARCHAR(128) DEFAULT NULL,
          ADD COLUMN `voice_status` TINYINT DEFAULT 0 COMMENT '0=未开始 1=生成中 2=成功 3=失败',
          ADD COLUMN `voice_error` VARCHAR(512) DEFAULT NULL
    """)

    # 4. storyboard_scene: 删除新字段 + sort_order 改回 INT
    op.execute("""
        ALTER TABLE `storyboard_scene`
          DROP COLUMN `video_prompt`,
          DROP COLUMN `video_type`,
          DROP COLUMN `selected_first_frame_id`,
          DROP COLUMN `selected_last_frame_id`,
          DROP COLUMN `selected_video_id`,
          DROP COLUMN `last_modified_user_id`,
          MODIFY COLUMN `sort_order` INT DEFAULT 0
    """)
