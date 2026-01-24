-- 世界表
-- World Table
-- 用于存储不同的世界观设定

CREATE TABLE IF NOT EXISTS `world` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `name` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '世界名称',
    `description` TEXT COMMENT '世界描述',
    `story_outline` TEXT COMMENT '故事大纲',
    `visual_style` TEXT COMMENT '画面风格',
    `era_environment` TEXT COMMENT '时代环境',
    `color_language` TEXT COMMENT '色彩语言',
    `composition_preference` TEXT COMMENT '构图倾向',
    `user_id` INT UNSIGNED NOT NULL COMMENT '创建者用户ID',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='世界表';
