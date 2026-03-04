-- 为世界表添加故事大纲字段
-- Add story outline field to world table
-- 用于存储世界观的故事大纲

ALTER TABLE `world` ADD COLUMN `story_outline` TEXT COMMENT '故事大纲' AFTER `description`;
