-- Migration script to add style and style_reference_image fields to video_workflow table
-- Run this script on existing databases to add the new fields

ALTER TABLE `video_workflow` 
ADD COLUMN `style` VARCHAR(255) DEFAULT NULL COMMENT '画风' AFTER `workflow_data`,
ADD COLUMN `style_reference_image` VARCHAR(500) DEFAULT NULL COMMENT '画风参考图URL' AFTER `style`;
