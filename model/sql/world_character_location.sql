-- 世界表
-- World Table
-- 用于存储不同的世界观设定

CREATE TABLE IF NOT EXISTS `world` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `name` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '世界名称',
    `description` TEXT COMMENT '世界描述',
    `user_id` INT UNSIGNED NOT NULL COMMENT '创建者用户ID',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='世界表';


-- 角色表
-- Character Table
-- 用于存储角色信息

CREATE TABLE IF NOT EXISTS `character` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `world_id` INT UNSIGNED NOT NULL COMMENT '所属世界ID',
    `name` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '角色姓名',
    `age` VARCHAR(50) DEFAULT NULL COMMENT '年龄',
    `occupation` VARCHAR(255) DEFAULT NULL COMMENT '职业',
    `identity` VARCHAR(255) DEFAULT NULL COMMENT '身份',
    `appearance` TEXT COMMENT '外貌描述',
    `personality` TEXT COMMENT '性格特征',
    `behavior_habits` TEXT COMMENT '行为习惯',
    `other_info` TEXT COMMENT '其他信息',
    `reference_image` VARCHAR(500) DEFAULT NULL COMMENT '参考图片地址',
    `default_voice` VARCHAR(500) DEFAULT NULL COMMENT '默认声音文件路径',
    `emotion_voices` JSON COMMENT '感情色彩声音(JSON格式)',
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


-- 场景/地点表
-- Location Table
-- 用于存储场景地点信息

CREATE TABLE IF NOT EXISTS `location` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `world_id` INT UNSIGNED NOT NULL COMMENT '所属世界ID',
    `name` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '地点名称',
    `parent_id` INT UNSIGNED DEFAULT NULL COMMENT '父级地点ID',
    `reference_image` VARCHAR(500) DEFAULT NULL COMMENT '参考图片',
    `description` TEXT COMMENT '地点描述',
    `user_id` INT UNSIGNED NOT NULL COMMENT '创建者用户ID',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    INDEX `idx_world_id` (`world_id`),
    INDEX `idx_parent_id` (`parent_id`),
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_name` (`name`),
    INDEX `idx_create_time` (`create_time`),
    CONSTRAINT `fk_location_world` FOREIGN KEY (`world_id`) REFERENCES `world` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_location_parent` FOREIGN KEY (`parent_id`) REFERENCES `location` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='场景地点表';
