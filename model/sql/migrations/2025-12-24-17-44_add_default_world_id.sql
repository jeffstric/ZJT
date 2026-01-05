-- Migration script to add default_world_id field to video_workflow table
-- Run this script on existing databases to add the new field

ALTER TABLE `video_workflow` 
ADD COLUMN `default_world_id` INT UNSIGNED DEFAULT NULL COMMENT '默认世界ID' AFTER `style_reference_image`;
