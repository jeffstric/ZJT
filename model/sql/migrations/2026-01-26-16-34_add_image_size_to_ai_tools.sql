-- 添加 image_size 字段到 ai_tools 表
-- Add image_size field to ai_tools table
-- 用于存储图片尺寸（1K, 2K, 4K）

ALTER TABLE `ai_tools` 
ADD COLUMN `image_size` VARCHAR(20) DEFAULT NULL COMMENT '图片尺寸（1K, 2K, 4K）' 
AFTER `message`;
