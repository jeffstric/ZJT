-- 视频工作流表
-- Video Workflow Table
-- 用于存储视频工作流的基本信息

CREATE TABLE IF NOT EXISTS `video_workflow` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `name` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '工作流名称',
    `description` TEXT COMMENT '工作流描述',
    `cover_image` VARCHAR(500) DEFAULT NULL COMMENT '封面图片URL',
    `user_id` INT UNSIGNED NOT NULL COMMENT '创建者用户ID',
    `status` TINYINT NOT NULL DEFAULT 1 COMMENT '状态: 0-禁用, 1-启用, 2-草稿',
    `workflow_data` JSON COMMENT '工作流配置数据(JSON格式)',
    `style` VARCHAR(255) DEFAULT NULL COMMENT '画风',
    `style_reference_image` VARCHAR(500) DEFAULT NULL COMMENT '画风参考图URL',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_status` (`status`),
    INDEX `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='视频工作流表';
