-- 添加 sora_character 字段到 character 表
-- Add sora_character field to character table
-- 用于存储Sora角色卡的任务ID

ALTER TABLE `character` 
ADD COLUMN `sora_character` VARCHAR(255) DEFAULT NULL COMMENT 'Sora角色卡任务ID' 
AFTER `emotion_voices`;
