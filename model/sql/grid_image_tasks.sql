-- 宫格生图任务表
-- Grid Image Tasks Table
-- 用于存储宫格生图任务信息，支持多进程环境下的任务状态共享
CREATE TABLE IF NOT EXISTS `grid_image_tasks` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `task_key` varchar(255) NOT NULL COMMENT '任务唯一键 (格式: item_type_item_name)',
  `project_id` varchar(100) NOT NULL COMMENT 'ComfyUI project_id',
  `item_type` tinyint NOT NULL COMMENT '项目类型 (1=character, 2=location, 3=props, 4=character_grid, 5=location_grid, 6=prop_grid)',
  `item_name` varchar(255) NOT NULL COMMENT '项目名称（宫格任务为逗号分隔的多个名称）',
  `user_id` varchar(50) NOT NULL COMMENT '用户ID',
  `world_id` varchar(50) NOT NULL COMMENT '世界观ID',
  `comfyui_base_url` varchar(500) NOT NULL COMMENT 'ComfyUI服务地址',
  `auth_token` varchar(500) NOT NULL COMMENT '认证令牌',
  `status` tinyint DEFAULT '0' COMMENT '状态（0-队列中, 1-处理中, 2-完成, -1-失败, -2-超时, -3-取消, -4-下载失败）',
  `try_count` int DEFAULT '0' COMMENT '尝试次数',
  `max_attempts` int DEFAULT '60' COMMENT '最大尝试次数',
  `error_message` text COMMENT '错误信息',
  `result_url` varchar(1000) DEFAULT NULL COMMENT '结果图片URL',
  `local_file_path` varchar(1000) DEFAULT NULL COMMENT '本地文件路径',
  `update_success` tinyint DEFAULT '0' COMMENT '是否成功更新到item (0-否, 1-是)',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `completed_at` datetime DEFAULT NULL COMMENT '完成时间',
  `failed_at` datetime DEFAULT NULL COMMENT '失败时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task_key` (`task_key`),
  KEY `idx_status` (`status`),
  KEY `idx_user_world` (`user_id`, `world_id`),
  KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='宫格生图任务表';
