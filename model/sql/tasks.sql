-- 任务表
-- Tasks Table
-- 用于存储任务信息
CREATE TABLE IF NOT EXISTS `tasks` (
  `id` int NOT NULL AUTO_INCREMENT,
  `task_type` varchar(50) NOT NULL COMMENT '任务类型',
  `task_id` int NOT NULL COMMENT '任务ID',
  `try_count` int DEFAULT '0' COMMENT '失败尝试次数',
  `next_trigger` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '下一次执行时间',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间',
  `status` tinyint DEFAULT '0' COMMENT '状态（0-队列中，1-处理中，2-处理完成，-1-处理失败）',
  PRIMARY KEY (`id`),
  KEY `idx_tasks_task_id` (`task_id`),
  KEY `idx_tasks_task_type` (`task_type`,`status`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='任务表';