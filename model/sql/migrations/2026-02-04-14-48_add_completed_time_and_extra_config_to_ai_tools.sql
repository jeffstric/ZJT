-- 添加 completed_time 和 extra_config 字段到 ai_tools 表
-- Add completed_time and extra_config fields to ai_tools table
-- completed_time: 记录任务完成时间
-- extra_config: 存储额外配置信息（JSON格式）

ALTER TABLE `ai_tools` 
ADD COLUMN `completed_time` DATETIME NULL DEFAULT NULL COMMENT '完成时间' AFTER `image_size`,
ADD COLUMN `extra_config` TEXT COMMENT '额外配置（JSON格式）' AFTER `completed_time`;
