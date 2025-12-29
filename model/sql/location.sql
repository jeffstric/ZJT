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
