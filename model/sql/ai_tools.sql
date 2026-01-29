-- AI Tools Table
-- 用于存储AI工具使用记录（图片编辑、视频生成等）

CREATE TABLE IF NOT EXISTS `ai_tools` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `prompt` TEXT COMMENT '提示词',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `update_time` DATETIME NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    `image_path` TEXT COMMENT '图片路径',
    `duration` TINYINT DEFAULT NULL COMMENT '时长',
    `ratio` VARCHAR(255) DEFAULT NULL COMMENT '视频比例（9:16, 16:9, 1:1, 3:4, 4:3）',
    `project_id` VARCHAR(100) DEFAULT NULL COMMENT '任务ID',
    `transaction_id` VARCHAR(100) DEFAULT NULL COMMENT '交易ID',
    `result_url` TEXT COMMENT '结果地址',
    `user_id` INT UNSIGNED DEFAULT NULL COMMENT '用户ID',
    `type` TINYINT DEFAULT NULL COMMENT '类型（1-图片编辑，2-AI视频生成，3-图片生成视频，4-图片高清）',
    `status` TINYINT DEFAULT NULL COMMENT '状态: 0-未处理, 1-正在处理, -1-处理失败, 2-处理完成',
    `message` TEXT COMMENT '错误信息',
    `image_size` VARCHAR(20) DEFAULT NULL COMMENT '图片尺寸（1K, 2K, 4K）',
    PRIMARY KEY (`id`),
    INDEX `idx_user_id_type_create_time` (`user_id`, `type`, `create_time`),
    INDEX `idx_user_id_create_time` (`user_id`, `create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI工具使用记录表';
