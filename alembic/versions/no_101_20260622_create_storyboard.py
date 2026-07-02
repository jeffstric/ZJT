"""Create storyboard and storyboard_scene tables

故事板模块：
- storyboard: 故事板主表（一集一板，关联世界/画风/集数）
- storyboard_scene: 分镜表（独立任务状态：图片/视频/配音）

Revision ID: 20260622_storyboard
Revises: 20260624_marketing_publications
Create Date: 2026-06-22
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '20260622_storyboard'
down_revision: Union[str, None] = '20260624_marketing_publications'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 storyboard 和 storyboard_scene 表"""
    op.execute("""
        CREATE TABLE IF NOT EXISTS `storyboard` (
            `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            `world_id` INT UNSIGNED NOT NULL COMMENT '关联世界ID',
            `user_id` INT UNSIGNED NOT NULL,
            `episode_number` INT NOT NULL DEFAULT 1 COMMENT '集数，一集一个故事板',
            `workflow_id` INT UNSIGNED DEFAULT NULL COMMENT '关联工作流ID（可选，一键转视频用）',
            `script_id` INT UNSIGNED DEFAULT NULL COMMENT '关联剧本ID',
            `title` VARCHAR(255) DEFAULT '' COMMENT '故事板标题',
            `total_duration` INT DEFAULT 0 COMMENT '总时长（秒）',
            `status` TINYINT DEFAULT 1 COMMENT '1=编辑中 2=已完成',
            `style` VARCHAR(255) DEFAULT NULL COMMENT '画风名称（同 video_workflow.style）',
            `style_reference_image` VARCHAR(500) DEFAULT NULL COMMENT '画风参考图URL',
            `workflow_ratio` VARCHAR(10) DEFAULT NULL COMMENT '画幅比例: 16:9 | 9:16',
            `config_json` JSON DEFAULT NULL COMMENT '全局配置: 分辨率/默认模型/UI状态',
            `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY `uk_user_world_episode` (`user_id`, `world_id`, `episode_number`),
            INDEX `idx_world_user` (`world_id`, `user_id`),
            INDEX `idx_workflow` (`workflow_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='故事板主表'
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS `storyboard_scene` (
            `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            `storyboard_id` INT UNSIGNED NOT NULL,
            `sort_order` INT DEFAULT 0,
            `title` VARCHAR(255) DEFAULT '',
            `duration` INT DEFAULT 5,
            `thumbnail_url` VARCHAR(512) DEFAULT NULL,
            `preview_image_url` VARCHAR(512) DEFAULT NULL,
            `prompt_json` JSON DEFAULT NULL COMMENT '画面提示词: perspective/style/scene_desc/char_desc',
            `voiceover_text` TEXT DEFAULT NULL COMMENT '配音台词',
            `voiceover_audio_url` VARCHAR(512) DEFAULT NULL,
            `voice_config_json` JSON DEFAULT NULL COMMENT '语速/音量/音色',
            `music_json` JSON DEFAULT NULL COMMENT '背景音乐配置',
            `first_frame_url` VARCHAR(512) DEFAULT NULL COMMENT '首帧图片',
            `last_frame_url` VARCHAR(512) DEFAULT NULL COMMENT '尾帧图片',
            `video_url` VARCHAR(512) DEFAULT NULL COMMENT '生成的视频',
            `video_config_json` JSON DEFAULT NULL COMMENT '分辨率/模型/时长',
            `image_task_id` VARCHAR(128) DEFAULT NULL,
            `image_status` TINYINT DEFAULT 0 COMMENT '0=未开始 1=生成中 2=成功 3=失败',
            `image_error` VARCHAR(512) DEFAULT NULL,
            `video_task_id` VARCHAR(128) DEFAULT NULL,
            `video_status` TINYINT DEFAULT 0 COMMENT '0=未开始 1=生成中 2=成功 3=失败',
            `video_error` VARCHAR(512) DEFAULT NULL,
            `voice_task_id` VARCHAR(128) DEFAULT NULL,
            `voice_status` TINYINT DEFAULT 0 COMMENT '0=未开始 1=生成中 2=成功 3=失败',
            `voice_error` VARCHAR(512) DEFAULT NULL,
            `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX `idx_storyboard` (`storyboard_id`),
            INDEX `idx_sort` (`storyboard_id`, `sort_order`),
            INDEX `idx_image_task` (`image_task_id`),
            INDEX `idx_video_task` (`video_task_id`),
            INDEX `idx_voice_task` (`voice_task_id`),
            FOREIGN KEY (`storyboard_id`) REFERENCES `storyboard`(`id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='故事板分镜表'
    """)


def downgrade() -> None:
    """回滚：删除 storyboard_scene 和 storyboard 表"""
    op.execute("DROP TABLE IF EXISTS `storyboard_scene`")
    op.execute("DROP TABLE IF EXISTS `storyboard`")
