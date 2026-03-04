-- 角色表
-- Character Table
-- 用于存储角色信息

CREATE TABLE IF NOT EXISTS `character` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `world_id` INT UNSIGNED NOT NULL COMMENT '所属世界ID',
    `name` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '角色姓名',
    `age` VARCHAR(50) DEFAULT NULL COMMENT '年龄',
    `identity` VARCHAR(255) DEFAULT NULL COMMENT '身份/职业',
    `appearance` TEXT COMMENT '外貌描述',
    `personality` TEXT COMMENT '性格特征',
    `behavior` TEXT COMMENT '行为习惯',
    `other_info` TEXT COMMENT '其他信息',
    `reference_image` VARCHAR(500) DEFAULT NULL COMMENT '参考图片地址',
    `default_voice` VARCHAR(500) DEFAULT NULL COMMENT '默认声音文件路径',
    `emotion_voices` JSON COMMENT '感情色彩声音(JSON格式)',
    `sora_character` VARCHAR(255) DEFAULT NULL COMMENT 'Sora角色卡任务ID',
    `user_id` INT UNSIGNED NOT NULL COMMENT '创建者用户ID',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    INDEX `idx_world_id` (`world_id`),
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_name` (`name`),
    INDEX `idx_create_time` (`create_time`),
    CONSTRAINT `fk_character_world` FOREIGN KEY (`world_id`) REFERENCES `world` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='角色表';
