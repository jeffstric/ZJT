-- 为世界表添加画面风格相关字段
-- Add visual style related fields to world table
-- 用于存储世界观的画面风格、时代环境、色彩语言和构图倾向设定

ALTER TABLE `world` ADD COLUMN `visual_style` TEXT COMMENT '画面风格' AFTER `story_outline`;
ALTER TABLE `world` ADD COLUMN `era_environment` TEXT COMMENT '时代环境' AFTER `visual_style`;
ALTER TABLE `world` ADD COLUMN `color_language` TEXT COMMENT '色彩语言' AFTER `era_environment`;
ALTER TABLE `world` ADD COLUMN `composition_preference` TEXT COMMENT '构图倾向' AFTER `color_language`;
