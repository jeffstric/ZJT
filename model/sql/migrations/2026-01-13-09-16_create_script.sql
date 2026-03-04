-- 创建剧本表
-- Create Script table
-- 用于存储剧本信息，关联世界观和用户

CREATE TABLE IF NOT EXISTS `script` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `world_id` INT UNSIGNED NOT NULL COMMENT '所属世界ID',
    `user_id` INT UNSIGNED NOT NULL COMMENT '创建者用户ID',
    `title` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '剧本标题',
    `episode_number` INT DEFAULT NULL COMMENT '计划第几集',
    `content` TEXT COMMENT '剧本内容',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    INDEX `idx_world_id` (`world_id`),
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_episode_number` (`episode_number`),
    INDEX `idx_create_time` (`create_time`),
    CONSTRAINT `fk_script_world` FOREIGN KEY (`world_id`) REFERENCES `world` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='剧本表';
