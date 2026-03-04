-- 创建 RunningHub 并发槽位管理表
-- Create RunningHub concurrency slots management table
-- 用于控制 RunningHub API 的并发请求数量，避免 TASK_QUEUE_MAXED 错误

CREATE TABLE IF NOT EXISTS `runninghub_slots` (
    `id` INT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `task_id` INT UNSIGNED NOT NULL COMMENT 'tasks表的task_id (ai_tools.id)',
    `task_table_id` INT UNSIGNED NOT NULL COMMENT 'tasks表的主键id',
    `project_id` VARCHAR(100) DEFAULT NULL COMMENT 'RunningHub项目ID（提交后才有）',
    `task_type` TINYINT NOT NULL COMMENT '任务类型(10-LTX2.0, 11-Wan2.2)',
    `status` TINYINT NOT NULL DEFAULT 1 COMMENT '状态: 1-槽位占用中, 2-已释放',
    `acquired_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '槽位获取时间',
    `released_at` DATETIME NULL DEFAULT NULL COMMENT '槽位释放时间',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_task_table_id` (`task_table_id`),
    INDEX `idx_status_task_type` (`status`, `task_type`),
    INDEX `idx_task_id` (`task_id`),
    INDEX `idx_project_id` (`project_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='RunningHub并发槽位管理表';
